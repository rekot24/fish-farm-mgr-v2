"""
capture/scrcpy_socket.py

Scrcpy socket capture backend — the primary capture backend.

How scrcpy socket works:
  1. Push the scrcpy-server.jar to the device via ADB
  2. Forward a local TCP port to the device's abstract socket
  3. Start the scrcpy server on the device as a background process
  4. Connect a local socket to the forwarded port
  5. Read and discard the 64-byte device info header
  6. Read the 12-byte video stream header (codec, width, height)
  7. Feed the H.264 bytestream into a PyAV decoder
  8. Yield decoded frames as BGR numpy arrays

Result: sub-100ms frame delivery, no visible window, scales to 10+ devices.

Dependencies:
  pip install av        (PyAV — ffmpeg Python bindings)
  pip install opencv-python numpy

The scrcpy-server.jar must be placed in:
  assets/scrcpy-server.jar   (relative to project root)

Download from: https://github.com/Genymobile/scrcpy/releases
Use the .jar file from any recent release (2.x).
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


# Port used for ADB forward. Each device needs a unique port if running
# multiple devices simultaneously. We compute it from the serial hash.
_BASE_PORT = 27183


def _port_for_serial(serial: str) -> int:
    """
    Assign a unique local port per device serial.
    Uses a hash to pick from a range of ports so they don't collide.
    Range: 27183 - 27283 (100 ports, enough for 100 devices).
    """
    return _BASE_PORT + (hash(serial) % SCRCPY_PORT_RANGE_SIZE)


class ScrcpySocketBackend(CaptureBackend):
    """
    Primary capture backend using scrcpy's server socket mode.

    Delivers frames as BGR numpy arrays with sub-100ms latency.
    No visible window on the PC. The device screen stays on (needed for ADB input).
    """

    # Scrcpy server constants
    _DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
    _HEADER_SIZE = 64          # device name header bytes to skip
    _VIDEO_HEADER_SIZE = 12    # codec + width + height

    def __init__(
        self,
        serial: str,
        adb_path: str = "adb",
        server_jar_path: str | None = None,
        max_size: int = 0,         # 0 = native resolution; set e.g. 720 to limit height
        bit_rate: int = 2_000_000, # 2 Mbps — low enough for USB, high enough for detection
        connect_timeout_s: float = 10.0,
        development_mode: bool = False,
    ):
        super().__init__(serial)
        self.adb_path = adb_path
        self.max_size = max_size
        self.bit_rate = bit_rate
        self.connect_timeout_s = connect_timeout_s
        # Layer 6 two-mode error handling, mirrors DeviceWorker._run() — see
        # _decode_loop() below. This backend runs its own background thread,
        # so it needs the same outermost-safety-net treatment DeviceWorker's
        # main loop got.
        self.development_mode = development_mode
        self.local_port = _port_for_serial(serial)

        # Resolve server jar path
        if server_jar_path:
            self._jar_path = Path(server_jar_path)
        else:
            # Default: assets/scrcpy-server.jar relative to project root
            self._jar_path = Path(__file__).resolve().parent.parent / "assets" / "scrcpy-server.jar"

        # Internal state
        self._sock: socket.socket | None = None
        self._server_proc: subprocess.Popen | None = None
        self._decoder = None  # av.CodecContext, set in connect()
        self._latest_frame: np.ndarray | None = None
        self._decode_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # CaptureBackend interface
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Full connection sequence:
          1. Verify jar exists
          2. Push jar to device
          3. Set up ADB port forward
          4. Start scrcpy server on device
          5. Open local socket connection
          6. Read and validate stream headers
          7. Start background decode thread
        """
        try:
            if not self._jar_path.exists():
                app_logger.log(f"[scrcpy] Server jar not found: {self._jar_path}", "ERROR")
                app_logger.log(f"[scrcpy] Download scrcpy-server.jar and place it at: {self._jar_path}", "ERROR")
                return False

            self._stop_event.clear()

            # 1. Push the server jar to device
            if not self._push_server():
                return False

            # 2. Forward the local port to the device's abstract socket
            if not self._setup_port_forward():
                return False

            # 3. Start the scrcpy server process on the device
            if not self._start_server():
                return False

            # 4. Give the server a moment to bind its socket
            time.sleep(SCRCPY_SERVER_BIND_SETTLE_S)

            # 5. Connect our local socket
            if not self._connect_socket():
                return False

            # 6. Read and validate the stream headers
            if not self._read_headers():
                return False

            # 7. Initialize PyAV H.264 decoder
            if not _AV_AVAILABLE:
                app_logger.log("[scrcpy] PyAV not installed. Run: pip install av", "ERROR")
                return False
            self._decoder = _av_module.CodecContext.create("h264", "r")

            # 8. Start the background thread that continuously decodes frames
            self._decode_thread = threading.Thread(
                target=self._decode_loop,
                daemon=True,
                name=f"scrcpy-decode-{self.serial[:8]}",
            )
            self._decode_thread.start()

            self._connected = True
            app_logger.log(f"[scrcpy] Connected to {self.serial} on port {self.local_port}", "INFO")
            return True

        except Exception as e:
            app_logger.log(f"[scrcpy] connect() failed for {self.serial}: {type(e).__name__}: {e}", "ERROR")
            self.disconnect()
            return False

    def get_frame(self) -> np.ndarray | None:
        """
        Return the most recently decoded frame.
        The decode thread updates _latest_frame continuously in the background.
        This call is non-blocking and returns immediately.
        """
        return self._latest_frame

    def disconnect(self) -> None:
        """Cleanly shut down: stop decode thread, close socket, kill server, remove forward."""
        self._stop_event.set()
        self._connected = False

        # Stop decode thread
        if self._decode_thread and self._decode_thread.is_alive():
            self._decode_thread.join(timeout=SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S)

        # Close socket
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        # Kill server process on device
        if self._server_proc:
            try:
                self._server_proc.terminate()
            except Exception:
                pass
            self._server_proc = None

        # Kill scrcpy server process on device side
        try:
            subprocess.run(
                [self.adb_path, "-s", self.serial, "shell",
                 "pkill", "-f", "scrcpy-server"],
                timeout=SCRCPY_TEARDOWN_TIMEOUT_S, capture_output=True,
            )
        except Exception:
            pass

        # Remove port forward
        try:
            subprocess.run(
                [self.adb_path, "-s", self.serial, "forward",
                 "--remove", f"tcp:{self.local_port}"],
                timeout=SCRCPY_TEARDOWN_TIMEOUT_S, capture_output=True,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal connection steps
    # ------------------------------------------------------------------

    def _adb(self, *args, timeout: float = ADB_DEFAULT_TIMEOUT_S, capture: bool = True) -> subprocess.CompletedProcess:
        """Run an adb command for this device."""
        cmd = [self.adb_path, "-s", self.serial] + list(args)
        return subprocess.run(cmd, capture_output=capture, timeout=timeout)

    def _push_server(self) -> bool:
        """Push scrcpy-server.jar to the device."""
        try:
            result = self._adb("push", str(self._jar_path), self._DEVICE_SERVER_PATH)
            if result.returncode != 0:
                app_logger.log(f"[scrcpy] Failed to push server jar to {self.serial}", "ERROR")
                return False
            return True
        except Exception as e:
            app_logger.log(f"[scrcpy] push_server error: {e}", "ERROR")
            return False

    def _setup_port_forward(self) -> bool:
        """Set up ADB TCP port forward."""
        try:
            result = self._adb(
                "forward", f"tcp:{self.local_port}", "localabstract:scrcpy"
            )
            if result.returncode != 0:
                app_logger.log(f"[scrcpy] Port forward failed for {self.serial}", "ERROR")
                return False
            return True
        except Exception as e:
            app_logger.log(f"[scrcpy] port_forward error: {e}", "ERROR")
            return False

    def _start_server(self) -> bool:
        """
        Start the scrcpy server on the device as a background process.
        We use Popen so it stays running while we connect.
        """
        try:
            cmd = [
                self.adb_path, "-s", self.serial, "shell",
                f"CLASSPATH={self._DEVICE_SERVER_PATH}",
                "app_process", "/",
                "com.genymobile.scrcpy.Server",
                "4.1",                          # version string (matches jar)
                "tunnel_forward=true",
                f"video_bit_rate={self.bit_rate}",
                f"max_size={self.max_size}",
                "control=false",                # capture only, no input forwarding
                "audio=false",                  # no audio stream
                "send_frame_meta=false",        # simpler stream format
            ]
            self._server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as e:
            app_logger.log(f"[scrcpy] start_server error: {e}", "ERROR")
            return False

    def _connect_socket(self) -> bool:
        """Open a TCP connection to the forwarded port."""
        deadline = time.time() + self.connect_timeout_s
        while time.time() < deadline:
            try:
                sock = socket.create_connection(
                    ("127.0.0.1", self.local_port), timeout=SCRCPY_SOCKET_CONNECT_ATTEMPT_TIMEOUT_S
                )
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._sock = sock
                return True
            except (ConnectionRefusedError, OSError):
                time.sleep(SCRCPY_SOCKET_RETRY_SLEEP_S)  # server not ready yet, retry
        app_logger.log(f"[scrcpy] Socket connection timed out for {self.serial}", "ERROR")
        return False

    def _read_headers(self) -> bool:
        """
        Read and validate the scrcpy stream headers.

        Scrcpy sends two headers after connection:
          - 64 bytes: device name (null-terminated string, padded)
          - 12 bytes: video codec info (codec id 4B + width 4B + height 4B)
        """
        try:
            # Read and discard device name header
            device_header = self._recv_exact(self._HEADER_SIZE)
            if not device_header:
                app_logger.log(f"[scrcpy] Failed to read device header from {self.serial}", "ERROR")
                return False

            device_name = device_header.rstrip(b"\x00").decode("utf-8", errors="replace")
            app_logger.log(f"[scrcpy] Device: {device_name}", "INFO")

            # Read video stream header
            video_header = self._recv_exact(self._VIDEO_HEADER_SIZE)
            if not video_header:
                app_logger.log(f"[scrcpy] Failed to read video header from {self.serial}", "ERROR")
                return False

            codec_id, width, height = struct.unpack(">III", video_header)
            app_logger.log(f"[scrcpy] Stream: codec={codec_id:#010x} size={width}x{height}", "INFO")
            return True

        except Exception as e:
            app_logger.log(f"[scrcpy] read_headers error: {e}", "ERROR")
            return False

    def _recv_exact(self, n: int) -> bytes | None:
        """Read exactly n bytes from the socket. Returns None on failure."""
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

    # ------------------------------------------------------------------
    # Background decode loop
    # ------------------------------------------------------------------

    def _decode_loop(self) -> None:
        """
        Background thread: continuously reads H.264 packets from the socket
        and decodes them into BGR frames.

        The latest decoded frame is stored in self._latest_frame.
        get_frame() reads from this without waiting.

        Scrcpy without send_frame_meta=true sends raw H.264 NAL units.
        PyAV handles reassembly.
        """
        buffer = b""
        chunk_size = 65536  # 64KB reads

        while not self._stop_event.is_set():
            try:
                # Read a chunk from the socket
                chunk = self._sock.recv(chunk_size)
                if not chunk:
                    # Server closed connection
                    break
                buffer += chunk

                # Feed all available data to the decoder
                try:
                    packets = self._decoder.parse(buffer)
                    buffer = b""  # parsed data is consumed

                    for packet in packets:
                        try:
                            frames = self._decoder.decode(packet)
                            for frame in frames:
                                # Convert PyAV VideoFrame to BGR numpy array
                                bgr_frame = frame.to_ndarray(format="bgr24")
                                self._latest_frame = bgr_frame
                        except Exception:
                            pass  # decode errors are not fatal, keep going

                except Exception:
                    pass  # parse errors are not fatal

            except (socket.timeout, TimeoutError):
                continue  # no data yet, loop again
            except Exception as e:
                # Layer 6 two-mode error handling, same pattern as
                # DeviceWorker._run(): always log, re-raise only in
                # development mode. In production this is unchanged — log
                # and end this thread; the device's frame capture stops,
                # which DeviceWorker already surfaces via its own
                # "Frame capture returned None" warning path.
                if not self._stop_event.is_set():
                    app_logger.log(f"[scrcpy] decode_loop error for {self.serial}: {e}", "ERROR")
                if self.development_mode and not self._stop_event.is_set():
                    raise
                break

        app_logger.log(f"[scrcpy] Decode loop ended for {self.serial}", "INFO")
