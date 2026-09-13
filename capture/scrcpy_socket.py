"""
capture/scrcpy_socket.py

Scrcpy socket capture backend — primary capture backend.
Uses the bundled adb.exe from tools/adb/ and scrcpy-server.jar from tools/scrcpy/.
See original file for full protocol documentation.
"""

from __future__ import annotations

import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

try:
    import av as _av_module
    _AV_AVAILABLE = True
except ImportError:
    _av_module = None
    _AV_AVAILABLE = False
import numpy as np
import cv2

from capture.base import CaptureBackend
from bot import app_logger
from config.constants import (
    ADB_DEFAULT_TIMEOUT_S, SCRCPY_PORT_RANGE_SIZE, SCRCPY_SERVER_BIND_SETTLE_S,
    SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S, SCRCPY_TEARDOWN_TIMEOUT_S,
    SCRCPY_SOCKET_CONNECT_ATTEMPT_TIMEOUT_S, SCRCPY_SOCKET_RETRY_SLEEP_S,
)
from config.paths import adb_exe, scrcpy_jar_path

_BASE_PORT = 27183


def _port_for_serial(serial: str) -> int:
    return _BASE_PORT + (hash(serial) % SCRCPY_PORT_RANGE_SIZE)


class ScrcpySocketBackend(CaptureBackend):
    """
    Primary capture backend using scrcpy's server socket mode.
    Delivers frames as BGR numpy arrays with sub-100ms latency.
    """

    _DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
    _HEADER_SIZE = 64
    _VIDEO_HEADER_SIZE = 12

    def __init__(
        self,
        serial: str,
        max_size: int = 0,
        bit_rate: int = 2_000_000,
        connect_timeout_s: float = 10.0,
        development_mode: bool = False,
    ):
        super().__init__(serial)
        self.max_size = max_size
        self.bit_rate = bit_rate
        self.connect_timeout_s = connect_timeout_s
        self.development_mode = development_mode
        self.local_port = _port_for_serial(serial)
        self._jar_path = scrcpy_jar_path()

        self._sock: socket.socket | None = None
        self._server_proc: subprocess.Popen | None = None
        self._decoder = None
        self._latest_frame: np.ndarray | None = None
        self._decode_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def connect(self) -> bool:
        try:
            if not self._jar_path.exists():
                app_logger.log(
                    f"[scrcpy] Server jar not found: {self._jar_path}", "ERROR")
                return False

            self._stop_event.clear()

            if not self._push_server():
                return False
            if not self._setup_port_forward():
                return False
            if not self._start_server():
                return False

            time.sleep(SCRCPY_SERVER_BIND_SETTLE_S)

            if not self._connect_socket():
                return False
            if not self._read_headers():
                return False

            if not _AV_AVAILABLE:
                app_logger.log("[scrcpy] PyAV not installed. Run: pip install av", "ERROR")
                return False
            self._decoder = _av_module.CodecContext.create("h264", "r")

            self._decode_thread = threading.Thread(
                target=self._decode_loop,
                daemon=True,
                name=f"scrcpy-decode-{self.serial[:8]}",
            )
            self._decode_thread.start()

            self._connected = True
            app_logger.log(
                f"[scrcpy] Connected to {self.serial} on port {self.local_port}", "INFO")
            return True

        except Exception as e:
            app_logger.log(
                f"[scrcpy] connect() failed for {self.serial}: {type(e).__name__}: {e}",
                "ERROR")
            self.disconnect()
            return False

    def get_frame(self) -> np.ndarray | None:
        return self._latest_frame

    def disconnect(self) -> None:
        self._stop_event.set()
        self._connected = False

        if self._decode_thread and self._decode_thread.is_alive():
            self._decode_thread.join(timeout=SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S)

        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        if self._server_proc:
            try:
                self._server_proc.terminate()
            except Exception:
                pass
            self._server_proc = None

        try:
            subprocess.run(
                [adb_exe(), "-s", self.serial, "shell", "pkill", "-f", "scrcpy-server"],
                timeout=SCRCPY_TEARDOWN_TIMEOUT_S, capture_output=True,
            )
        except Exception:
            pass

        try:
            subprocess.run(
                [adb_exe(), "-s", self.serial, "forward",
                 "--remove", f"tcp:{self.local_port}"],
                timeout=SCRCPY_TEARDOWN_TIMEOUT_S, capture_output=True,
            )
        except Exception:
            pass

    def _adb(self, *args, timeout: float = ADB_DEFAULT_TIMEOUT_S,
             capture: bool = True) -> subprocess.CompletedProcess:
        cmd = [adb_exe(), "-s", self.serial] + list(args)
        return subprocess.run(cmd, capture_output=capture, timeout=timeout)

    def _push_server(self) -> bool:
        try:
            result = self._adb("push", str(self._jar_path), self._DEVICE_SERVER_PATH)
            if result.returncode != 0:
                app_logger.log(
                    f"[scrcpy] Failed to push server jar to {self.serial}", "ERROR")
                return False
            return True
        except Exception as e:
            app_logger.log(f"[scrcpy] push_server error: {e}", "ERROR")
            return False

    def _setup_port_forward(self) -> bool:
        try:
            result = self._adb(
                "forward", f"tcp:{self.local_port}", "localabstract:scrcpy")
            if result.returncode != 0:
                app_logger.log(
                    f"[scrcpy] Port forward failed for {self.serial}", "ERROR")
                return False
            return True
        except Exception as e:
            app_logger.log(f"[scrcpy] port_forward error: {e}", "ERROR")
            return False

    def _start_server(self) -> bool:
        try:
            cmd = [
                adb_exe(), "-s", self.serial, "shell",
                f"CLASSPATH={self._DEVICE_SERVER_PATH}",
                "app_process", "/",
                "com.genymobile.scrcpy.Server",
                "4.1",
                "tunnel_forward=true",
                f"video_bit_rate={self.bit_rate}",
                f"max_size={self.max_size}",
                "control=false",
                "audio=false",
                "send_frame_meta=false",
            ]
            self._server_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            app_logger.log(f"[scrcpy] start_server error: {e}", "ERROR")
            return False

    def _connect_socket(self) -> bool:
        deadline = time.time() + self.connect_timeout_s
        while time.time() < deadline:
            try:
                sock = socket.create_connection(
                    ("127.0.0.1", self.local_port),
                    timeout=SCRCPY_SOCKET_CONNECT_ATTEMPT_TIMEOUT_S)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._sock = sock
                return True
            except (ConnectionRefusedError, OSError):
                time.sleep(SCRCPY_SOCKET_RETRY_SLEEP_S)
        app_logger.log(
            f"[scrcpy] Socket connection timed out for {self.serial}", "ERROR")
        return False

    def _read_headers(self) -> bool:
        try:
            device_header = self._recv_exact(self._HEADER_SIZE)
            if not device_header:
                app_logger.log(
                    f"[scrcpy] Failed to read device header from {self.serial}", "ERROR")
                return False
            device_name = device_header.rstrip(b"\x00").decode("utf-8", errors="replace")
            app_logger.log(f"[scrcpy] Device: {device_name}", "INFO")

            video_header = self._recv_exact(self._VIDEO_HEADER_SIZE)
            if not video_header:
                app_logger.log(
                    f"[scrcpy] Failed to read video header from {self.serial}", "ERROR")
                return False
            codec_id, width, height = struct.unpack(">III", video_header)
            app_logger.log(
                f"[scrcpy] Stream: codec={codec_id:#010x} size={width}x{height}", "INFO")
            return True
        except Exception as e:
            app_logger.log(f"[scrcpy] read_headers error: {e}", "ERROR")
            return False

    def _recv_exact(self, n: int) -> bytes | None:
        buf = b""
        while len(buf) < n:
            try:
                chunk = self._sock.recv(n - len(buf))
                if not chunk:
                    return None
                buf += chunk
            except Exception:
                return None
        return buf

    def _decode_loop(self) -> None:
        buffer = b""
        chunk_size = 65536
        while not self._stop_event.is_set():
            try:
                chunk = self._sock.recv(chunk_size)
                if not chunk:
                    break
                buffer += chunk
                try:
                    packets = self._decoder.parse(buffer)
                    buffer = b""
                    for packet in packets:
                        try:
                            frames = self._decoder.decode(packet)
                            for frame in frames:
                                self._latest_frame = frame.to_ndarray(format="bgr24")
                        except Exception:
                            pass
                except Exception:
                    pass
            except (socket.timeout, TimeoutError):
                continue
            except Exception as e:
                if not self._stop_event.is_set():
                    app_logger.log(
                        f"[scrcpy] decode_loop error for {self.serial}: {e}", "ERROR")
                if self.development_mode and not self._stop_event.is_set():
                    raise
                break
        app_logger.log(f"[scrcpy] Decode loop ended for {self.serial}", "INFO")
