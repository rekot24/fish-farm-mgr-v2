"""
capture/scrcpy_socket.py

Scrcpy socket capture backend — primary capture backend.
Uses the bundled adb.exe from tools/adb/ and scrcpy-server.jar from tools/scrcpy/.

The backend speaks the scrcpy 4.1 socket protocol directly. It keeps scrcpy
frame metadata enabled so MediaCodec packet boundaries are preserved, handles
the forward-tunnel dummy byte and video session metadata, and supports both
Annex-B and AVCC H.264 encoder output.
"""

from __future__ import annotations

import socket
import struct
import subprocess
import threading
import time

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
    ADB_DEFAULT_TIMEOUT_S,
    SCRCPY_DECODE_FRAME_INTERVAL_S,
    SCRCPY_PORT_RANGE_SIZE,
    SCRCPY_SERVER_BIND_SETTLE_S,
    SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S,
    SCRCPY_TEARDOWN_TIMEOUT_S,
    SCRCPY_SOCKET_CONNECT_ATTEMPT_TIMEOUT_S,
    SCRCPY_SOCKET_RETRY_SLEEP_S,
)
from config.paths import adb_exe, scrcpy_jar_path

_BASE_PORT = 27183
RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY_S = 2.0
ADB_RECONNECT_WAIT_S = 30.0
ADB_RECONNECT_POLL_S = 1.0
ADB_HEALTHCHECK_TIMEOUT_S = 3.0
ADB_TRANSPORT_RECOVERY_ATTEMPTS = 2

_H264_CODEC_ID = 0x68323634
_PACKET_FLAG_SESSION = 1 << 63
_PACKET_FLAG_CONFIG = 1 << 62
_PACKET_FLAG_KEY = 1 << 61
_PTS_MASK = (1 << 61) - 1
_MAX_PACKET_SIZE = 32 * 1024 * 1024


def _port_for_serial(serial: str) -> int:
    return _BASE_PORT + (hash(serial) % SCRCPY_PORT_RANGE_SIZE)


class ScrcpySocketBackend(CaptureBackend):
    """Primary capture backend using scrcpy's server socket mode."""

    _DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
    _HEADER_SIZE = 64
    _CODEC_HEADER_SIZE = 4
    _PACKET_HEADER_SIZE = 12

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
        # monotonic time of the last BGR conversion stored; -inf = none yet
        self._last_store_at: float = float("-inf")
        self._decode_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._decode_error_count = 0
        self._packet_count = 0
        self._h264_packet_format: str | None = None
        self._h264_annexb_config: bytes | None = None
        self._prefer_opencv_yuv = False

    def connect(self) -> bool:
        try:
            # Clear any stale scrcpy-server process or port forward left over
            # from a previous failed session before attempting a new connection.
            self._reset_transport_for_retry()
            
            if not self._jar_path.exists():
                app_logger.log(
                    f"[scrcpy] Server jar not found: {self._jar_path}", "ERROR"
                )
                self.disconnect()
                return False

            self._stop_event.clear()
            self._reset_decoder_state()

            if not self._recover_adb_transport():
                app_logger.log(
                    f"[scrcpy] ADB transport could not be recovered for "
                    f"{self.serial}",
                    "ERROR",
                )
                self.disconnect()
                return False

            if not self._push_server():
                self.disconnect()
                return False
            if not self._setup_port_forward():
                self.disconnect()
                return False
            if not self._start_server():
                self.disconnect()
                return False

            time.sleep(SCRCPY_SERVER_BIND_SETTLE_S)

            if not self._connect_socket():
                self.disconnect()
                return False
            if not self._read_headers():
                self.disconnect()
                return False

            if not _AV_AVAILABLE:
                app_logger.log(
                    "[scrcpy] PyAV not installed. Run: pip install av", "ERROR"
                )
                self.disconnect()
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
                f"[scrcpy] Connected to {self.serial} on port {self.local_port}",
                "INFO",
            )
            return True

        except Exception as e:
            app_logger.log(
                f"[scrcpy] connect() failed for {self.serial}: "
                f"{type(e).__name__}: {e}",
                "ERROR",
            )
            self.disconnect()
            return False

    def get_frame(self) -> np.ndarray | None:
        return self._latest_frame

    def disconnect(self) -> None:
        """Fully tear down this device's local and remote scrcpy session."""
        self._stop_event.set()
        self._connected = False

        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        if (
            self._decode_thread
            and self._decode_thread.is_alive()
            and threading.current_thread() is not self._decode_thread
        ):
            self._decode_thread.join(timeout=SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S)
        self._decode_thread = None

        if self._server_proc:
            try:
                self._server_proc.terminate()
            except Exception:
                pass
            self._server_proc = None

        self._kill_remote_scrcpy_processes()
        self._remove_port_forward()
        self._reset_decoder_state()

    def _reset_decoder_state(self) -> None:
        self._decoder = None
        self._latest_frame = None
        self._last_store_at = float("-inf")
        self._decode_error_count = 0
        self._packet_count = 0
        self._h264_packet_format = None
        self._h264_annexb_config = None
        self._prefer_opencv_yuv = False

    def _adb(
        self,
        *args,
        timeout: float = ADB_DEFAULT_TIMEOUT_S,
        capture: bool = True,
    ) -> subprocess.CompletedProcess:
        cmd = [adb_exe(), "-s", self.serial] + list(args)
        return subprocess.run(cmd, capture_output=capture, timeout=timeout)

    def _adb_online(self) -> bool:
        """Return True only when this exact device is currently online in ADB."""
        try:
            result = self._adb("get-state", timeout=2.0)
            return (
                result.returncode == 0
                and result.stdout.decode("utf-8", errors="replace").strip() == "device"
            )
        except Exception:
            return False

    def _adb_healthy(self) -> bool:
        """
        Verify that the transport can execute a real command, not merely that
        the serial appears in 'adb devices'. A poisoned USB transport may still
        report state=device while shell/push operations hang.
        """
        try:
            result = self._adb(
                "shell", "echo", "__fishfarm_adb_ok__",
                timeout=ADB_HEALTHCHECK_TIMEOUT_S,
            )
            if result.returncode != 0:
                return False
            output = result.stdout.decode("utf-8", errors="replace")
            return "__fishfarm_adb_ok__" in output
        except Exception:
            return False

    def _recover_adb_transport(self) -> bool:
        """
        Recover a device whose ADB transport is present but unresponsive.

        Uses only per-device operations so one flaky handset does not disturb
        the other phones attached to the same ADB server.
        """
        if self._adb_healthy():
            return True

        app_logger.log(
            f"[scrcpy] ADB transport unhealthy for {self.serial} — "
            f"attempting per-device recovery",
            "WARNING",
        )

        for attempt in range(1, ADB_TRANSPORT_RECOVERY_ATTEMPTS + 1):
            if self._stop_event.is_set():
                return False

            # Ask the host-side ADB server to tear down and recreate this
            # device transport. Do not use kill-server: that would disrupt
            # every other connected phone.
            try:
                subprocess.run(
                    [adb_exe(), "-s", self.serial, "reconnect"],
                    timeout=ADB_HEALTHCHECK_TIMEOUT_S,
                    capture_output=True,
                )
            except Exception:
                pass

            # If the transport is wedged badly enough that reconnect could not
            # clear it, request a USB adbd restart as a second per-device nudge.
            if not self._wait_for_adb_online(timeout_s=10.0):
                try:
                    subprocess.run(
                        [adb_exe(), "-s", self.serial, "usb"],
                        timeout=ADB_HEALTHCHECK_TIMEOUT_S,
                        capture_output=True,
                    )
                except Exception:
                    pass

            if self._wait_for_adb_online(timeout_s=ADB_RECONNECT_WAIT_S):
                # 'device' state can arrive before shell is actually usable.
                # Give adbd a short settle window and require a real round-trip.
                health_deadline = time.monotonic() + 10.0
                while (
                    not self._stop_event.is_set()
                    and time.monotonic() < health_deadline
                ):
                    if self._adb_healthy():
                        app_logger.log(
                            f"[scrcpy] ADB transport recovered for {self.serial}",
                            "INFO",
                        )
                        return True
                    time.sleep(ADB_RECONNECT_POLL_S)

            app_logger.log(
                f"[scrcpy] ADB transport recovery attempt "
                f"{attempt}/{ADB_TRANSPORT_RECOVERY_ATTEMPTS} failed "
                f"for {self.serial}",
                "WARNING",
            )

        return False

    def _wait_for_adb_online(self, timeout_s: float = ADB_RECONNECT_WAIT_S) -> bool:
        """Wait for a transient USB/ADB reset without giving up the worker."""
        deadline = time.monotonic() + timeout_s
        logged_wait = False

        while not self._stop_event.is_set() and time.monotonic() < deadline:
            if self._adb_online():
                if logged_wait:
                    app_logger.log(
                        f"[scrcpy] ADB transport recovered for {self.serial}",
                        "INFO",
                    )
                return True

            if not logged_wait:
                logged_wait = True
                app_logger.log(
                    f"[scrcpy] Waiting up to {timeout_s:.0f}s for ADB to return "
                    f"for {self.serial}",
                    "WARNING",
                )
            time.sleep(ADB_RECONNECT_POLL_S)

        return False

    def _kill_remote_scrcpy_processes(self) -> None:
        script = (
            'for p in $(pidof app_process 2>/dev/null); do '
            'c=$(cat /proc/$p/cmdline 2>/dev/null); '
            'case "$c" in '
            '*com.genymobile.scrcpy.Server*|*com.genymobile.scrcpy.Cleanup*) '
            'kill -9 $p 2>/dev/null;; '
            'esac; '
            'done'
        )
        try:
            subprocess.run(
                [adb_exe(), "-s", self.serial, "shell", script],
                timeout=SCRCPY_TEARDOWN_TIMEOUT_S,
                capture_output=True,
            )
        except Exception:
            pass

    def _remove_port_forward(self) -> None:
        try:
            subprocess.run(
                [
                    adb_exe(),
                    "-s",
                    self.serial,
                    "forward",
                    "--remove",
                    f"tcp:{self.local_port}",
                ],
                timeout=SCRCPY_TEARDOWN_TIMEOUT_S,
                capture_output=True,
            )
        except Exception:
            pass

    def _reset_transport_for_retry(self) -> None:
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

        self._kill_remote_scrcpy_processes()
        self._remove_port_forward()
        self._reset_decoder_state()

    def _push_server(self) -> bool:
        try:
            result = self._adb("push", str(self._jar_path), self._DEVICE_SERVER_PATH)
            if result.returncode != 0:
                stdout = result.stdout.decode("utf-8", errors="replace").strip()
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                app_logger.log(
                    f"[scrcpy] Failed to push server jar to {self.serial}: "
                    f"rc={result.returncode} stdout={stdout!r} stderr={stderr!r}",
                    "ERROR",
                )
                return False
            return True
        except Exception as e:
            app_logger.log(f"[scrcpy] push_server error: {e}", "ERROR")
            return False

    def _setup_port_forward(self) -> bool:
        try:
            result = self._adb(
                "forward", f"tcp:{self.local_port}", "localabstract:scrcpy"
            )
            if result.returncode != 0:
                app_logger.log(
                    f"[scrcpy] Port forward failed for {self.serial}", "ERROR"
                )
                return False
            return True
        except Exception as e:
            app_logger.log(f"[scrcpy] port_forward error: {e}", "ERROR")
            return False

    def _start_server(self) -> bool:
        try:
            cmd = [
                adb_exe(),
                "-s",
                self.serial,
                "shell",
                f"CLASSPATH={self._DEVICE_SERVER_PATH}",
                "app_process",
                "/",
                "com.genymobile.scrcpy.Server",
                "4.1",
                "tunnel_forward=true",
                f"video_bit_rate={self.bit_rate}",
                f"max_size={self.max_size}",
                "control=false",
                "audio=false",
                "send_frame_meta=true",
            ]
            self._server_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return True
        except Exception as e:
            app_logger.log(f"[scrcpy] start_server error: {e}", "ERROR")
            return False

    def _connect_socket(self) -> bool:
        deadline = time.time() + self.connect_timeout_s
        while time.time() < deadline and not self._stop_event.is_set():
            try:
                sock = socket.create_connection(
                    ("127.0.0.1", self.local_port),
                    timeout=SCRCPY_SOCKET_CONNECT_ATTEMPT_TIMEOUT_S,
                )
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._sock = sock
                return True
            except (ConnectionRefusedError, OSError):
                time.sleep(SCRCPY_SOCKET_RETRY_SLEEP_S)

        app_logger.log(
            f"[scrcpy] Socket connection timed out for {self.serial}", "ERROR"
        )
        return False

    def _read_headers(self) -> bool:
        try:
            first_byte = self._recv_exact(1)
            if not first_byte:
                app_logger.log(
                    f"[scrcpy] Failed to read stream prefix from {self.serial}",
                    "ERROR",
                )
                return False

            if first_byte == b"\x00":
                device_header = self._recv_exact(self._HEADER_SIZE)
                app_logger.log(
                    f"[scrcpy] Consumed forward-tunnel dummy byte for {self.serial}",
                    "DEBUG",
                )
            else:
                remainder = self._recv_exact(self._HEADER_SIZE - 1)
                device_header = first_byte + remainder if remainder else None

            if not device_header:
                app_logger.log(
                    f"[scrcpy] Failed to read device header from {self.serial}",
                    "ERROR",
                )
                return False

            device_name = device_header.rstrip(b"\x00").decode(
                "utf-8", errors="replace"
            )
            app_logger.log(f"[scrcpy] Device: {device_name}", "INFO")

            codec_header = self._recv_exact(self._CODEC_HEADER_SIZE)
            if not codec_header:
                app_logger.log(
                    f"[scrcpy] Failed to read codec id from {self.serial}", "ERROR"
                )
                return False

            codec_id = struct.unpack(">I", codec_header)[0]
            if codec_id != _H264_CODEC_ID:
                app_logger.log(
                    f"[scrcpy] Unsupported codec from {self.serial}: "
                    f"{codec_id:#010x}; expected H264={_H264_CODEC_ID:#010x}",
                    "ERROR",
                )
                return False

            session_header = self._recv_exact(self._PACKET_HEADER_SIZE)
            if not session_header:
                app_logger.log(
                    f"[scrcpy] Failed to read video session metadata from {self.serial}",
                    "ERROR",
                )
                return False

            flags, width, height = struct.unpack(">III", session_header)
            if not (flags & 0x80000000):
                app_logger.log(
                    f"[scrcpy] Invalid session packet from {self.serial}: "
                    f"flags={flags:#010x} size={width}x{height}",
                    "ERROR",
                )
                return False

            app_logger.log(
                f"[scrcpy] Stream: codec={codec_id:#010x} size={width}x{height}",
                "INFO",
            )
            return True
        except Exception as e:
            app_logger.log(f"[scrcpy] read_headers error: {e}", "ERROR")
            return False

    def _recv_exact(self, n: int) -> bytes | None:
        buf = b""
        while len(buf) < n and not self._stop_event.is_set():
            try:
                chunk = self._sock.recv(n - len(buf))
                if not chunk:
                    return None
                buf += chunk
            except Exception:
                return None
        return buf if len(buf) == n else None

    @staticmethod
    def _normalize_h264_payload(payload: bytes) -> bytes:
        """Preserve Annex-B H264; convert 4-byte length-prefixed NALs to Annex-B."""
        if payload.startswith(b"\x00\x00\x00\x01") or payload.startswith(
            b"\x00\x00\x01"
        ):
            return payload

        offset = 0
        out = bytearray()
        nal_count = 0
        size = len(payload)
        while offset + 4 <= size:
            nal_size = int.from_bytes(payload[offset : offset + 4], "big")
            if nal_size <= 0 or offset + 4 + nal_size > size:
                return payload
            out += b"\x00\x00\x00\x01"
            out += payload[offset + 4 : offset + 4 + nal_size]
            offset += 4 + nal_size
            nal_count += 1

        if offset == size and nal_count:
            return bytes(out)
        return payload

    def _apply_h264_config(self, payload: bytes) -> None:
        """Configure a fresh decoder for this encoder's H264 packet format."""
        if payload and payload[0] == 1:
            self._h264_packet_format = "avcc"
            self._h264_annexb_config = None
            decoder = _av_module.CodecContext.create("h264", "r")
            decoder.extradata = payload
            self._decoder = decoder
        else:
            self._h264_packet_format = "annexb"
            self._h264_annexb_config = self._normalize_h264_payload(payload)
            self._decoder = _av_module.CodecContext.create("h264", "r")

        self._decode_error_count = 0
        app_logger.log(
            f"[scrcpy] Applied H264 codec config for {self.serial}: "
            f"format={self._h264_packet_format} bytes={len(payload)} "
            f"head={payload[:16].hex()}",
            "INFO",
        )

    @staticmethod
    def _opencv_yuv_to_bgr(frame) -> np.ndarray:
        """Convert common decoder-native YUV layouts to BGR with OpenCV."""
        fmt = frame.format.name if frame.format else "unknown"
        native = frame.to_ndarray()

        if fmt in ("yuv420p", "yuvj420p"):
            return cv2.cvtColor(native, cv2.COLOR_YUV2BGR_I420)
        if fmt == "nv12":
            return cv2.cvtColor(native, cv2.COLOR_YUV2BGR_NV12)
        if fmt == "nv21":
            return cv2.cvtColor(native, cv2.COLOR_YUV2BGR_NV21)

        # Last fallback: ask PyAV only for planar YUV, not RGB. This avoids
        # the swscale RGB colorspace path that fails for some Samsung metadata.
        yuv = frame.to_ndarray(format="yuv420p")
        return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)

    def _frame_to_bgr(self, frame) -> np.ndarray:
        """
        Convert a decoded frame to BGR.

        Once FFmpeg's RGB conversion is known to be unsupported for this
        device/session, stay on the working OpenCV YUV path instead of throwing
        and logging the same swscale error for every frame.
        """
        if self._prefer_opencv_yuv:
            return self._opencv_yuv_to_bgr(frame)

        try:
            return frame.to_ndarray(format="bgr24")
        except Exception as primary_error:
            fmt = frame.format.name if frame.format else "unknown"
            self._prefer_opencv_yuv = True
            app_logger.log(
                f"[scrcpy] FFmpeg BGR conversion unsupported for {self.serial}: "
                f"format={fmt} size={frame.width}x{frame.height} "
                f"colorspace={getattr(frame, 'colorspace', None)} "
                f"primaries={getattr(frame, 'color_primaries', None)} "
                f"range={getattr(frame, 'color_range', None)}: "
                f"{type(primary_error).__name__}: {primary_error}; "
                f"using OpenCV YUV conversion for this session",
                "WARNING",
            )
            return self._opencv_yuv_to_bgr(frame)

    def _store_frames(self, frames) -> None:
        """
        Keep the newest decoded frame as a BGR array, converting at most once
        per SCRCPY_DECODE_FRAME_INTERVAL_S.

        The H.264 decode has already happened by the time frames reach here, so
        skipping a frame costs nothing in stream correctness. Only the expensive
        YUV->BGR conversion is skipped. This must NOT sleep or block: this runs
        on the decode thread, which is also the thread that drains the socket.
        Pausing it would let the scrcpy server's output queue back up and turn
        _latest_frame into minutes-old video.
        """
        for frame in frames:
            if time.monotonic() - self._last_store_at < SCRCPY_DECODE_FRAME_INTERVAL_S:
                continue
            try:
                self._latest_frame = self._frame_to_bgr(frame)
                # Advance only after a successful conversion so a failed one is
                # retried on the very next frame instead of waiting out the window.
                self._last_store_at = time.monotonic()
            except Exception as e:
                app_logger.log(
                    f"[scrcpy] Frame conversion error for {self.serial}: "
                    f"{type(e).__name__}: {e}",
                    "ERROR",
                )

    def _decode_annexb(self, packet_data: bytes) -> None:
        """
        Feed validated Annex-B bytes through FFmpeg's H.264 parser first.

        MediaCodec packet boundaries are not necessarily FFmpeg access-unit
        boundaries. The parser assembles SPS/PPS/slices into decoder-ready
        packets while keeping scrcpy protocol metadata completely out of the
        elementary stream.

        Do not copy scrcpy's microsecond PTS directly onto PyAV packets here.
        This capture backend only needs the newest decoded frame, and assigning
        timestamps without a matching time_base can make FFmpeg reject otherwise
        valid packets on some platforms/builds.
        """
        parsed_packets = self._decoder.parse(packet_data)
        for parsed in parsed_packets:
            self._store_frames(self._decoder.decode(parsed))

    def _decode_loop(self) -> None:
        unexpected_exit = False
        first_payload_logged = False
        first_media_logged = False

        while not self._stop_event.is_set():
            try:
                header = self._recv_exact(self._PACKET_HEADER_SIZE)
                if not header:
                    break

                first_u64 = struct.unpack(">Q", header[:8])[0]
                if first_u64 & _PACKET_FLAG_SESSION:
                    flags, width, height = struct.unpack(">III", header)
                    app_logger.log(
                        f"[scrcpy] New video session for {self.serial}: "
                        f"size={width}x{height} flags={flags:#010x}",
                        "INFO",
                    )
                    continue

                pts_flags, packet_size = struct.unpack(">QI", header)
                if packet_size <= 0 or packet_size > _MAX_PACKET_SIZE:
                    app_logger.log(
                        f"[scrcpy] Invalid H264 packet size for {self.serial}: "
                        f"{packet_size}",
                        "ERROR",
                    )
                    unexpected_exit = True
                    break

                payload = self._recv_exact(packet_size)
                if not payload:
                    break

                self._packet_count += 1
                is_config = bool(pts_flags & _PACKET_FLAG_CONFIG)
                is_key = bool(pts_flags & _PACKET_FLAG_KEY)
                pts = pts_flags & _PTS_MASK

                if not first_payload_logged:
                    first_payload_logged = True
                    app_logger.log(
                        f"[scrcpy] First H264 packet {self.serial}: "
                        f"bytes={len(payload)} config={is_config} key={is_key} "
                        f"head={payload[:16].hex()}",
                        "DEBUG",
                    )

                if is_config:
                    try:
                        self._apply_h264_config(payload)
                    except Exception as e:
                        self._decode_error_count += 1
                        app_logger.log(
                            f"[scrcpy] H264 config error for {self.serial} "
                            f"packet={self._packet_count} bytes={len(payload)}: "
                            f"{type(e).__name__}: {e}",
                            "ERROR",
                        )
                    continue

                if self._h264_packet_format == "avcc":
                    packet_data = payload
                else:
                    packet_data = self._normalize_h264_payload(payload)
                    if is_key and self._h264_annexb_config:
                        packet_data = self._h264_annexb_config + packet_data

                if not first_media_logged:
                    first_media_logged = True
                    app_logger.log(
                        f"[scrcpy] First media packet {self.serial}: "
                        f"bytes={len(payload)} key={is_key} "
                        f"format={self._h264_packet_format} "
                        f"head={payload[:24].hex()}",
                        "INFO",
                    )

                try:
                    if self._h264_packet_format == "avcc":
                        packet = _av_module.Packet(packet_data)
                        self._store_frames(self._decoder.decode(packet))
                    else:
                        self._decode_annexb(packet_data)
                except Exception as e:
                    self._decode_error_count += 1
                    if self._decode_error_count <= 5:
                        app_logger.log(
                            f"[scrcpy] H264 decode error for {self.serial} "
                            f"packet={self._packet_count} bytes={len(payload)} "
                            f"config={is_config} key={is_key} "
                            f"format={self._h264_packet_format}: "
                            f"{type(e).__name__}: {e}",
                            "ERROR",
                        )

            except (socket.timeout, TimeoutError):
                continue
            except Exception as e:
                if not self._stop_event.is_set():
                    app_logger.log(
                        f"[scrcpy] decode_loop error for {self.serial}: {e}", "ERROR"
                    )
                    unexpected_exit = True
                if self.development_mode and not self._stop_event.is_set():
                    raise
                break

        app_logger.log(f"[scrcpy] Decode loop ended for {self.serial}", "INFO")

        if self._stop_event.is_set():
            return

        if unexpected_exit or not self._stop_event.is_set():
            self._attempt_reconnect()

    def _attempt_reconnect(self) -> None:
        if self._stop_event.is_set():
            return

        self._reconnecting = True
        app_logger.log(
            f"[scrcpy] Unexpected disconnect for {self.serial} — "
            f"starting transport recovery",
            "WARNING",
        )

        try:
            self._reset_transport_for_retry()

            for attempt in range(1, RECONNECT_ATTEMPTS + 1):
                if self._stop_event.is_set():
                    return

                if not self._wait_for_adb_online():
                    app_logger.log(
                        f"[scrcpy] ADB did not return for {self.serial} "
                        f"during reconnect attempt {attempt}/{RECONNECT_ATTEMPTS}",
                        "WARNING",
                    )
                    continue

                if not self._recover_adb_transport():
                    app_logger.log(
                        f"[scrcpy] ADB returned but remained unhealthy for "
                        f"{self.serial} during reconnect attempt "
                        f"{attempt}/{RECONNECT_ATTEMPTS}",
                        "WARNING",
                    )
                    continue

                app_logger.log(
                    f"[scrcpy] Reconnect attempt {attempt}/{RECONNECT_ATTEMPTS} "
                    f"for {self.serial}",
                    "INFO",
                )

                if attempt > 1:
                    time.sleep(RECONNECT_DELAY_S)

                if self._stop_event.is_set():
                    return

                try:
                    if not self._push_server():
                        self._reset_transport_for_retry()
                        continue
                    if not self._setup_port_forward():
                        self._reset_transport_for_retry()
                        continue
                    if not self._start_server():
                        self._reset_transport_for_retry()
                        continue

                    time.sleep(SCRCPY_SERVER_BIND_SETTLE_S)

                    if self._stop_event.is_set():
                        self._reset_transport_for_retry()
                        return
                    if not self._connect_socket():
                        self._reset_transport_for_retry()
                        continue
                    if not self._read_headers():
                        self._reset_transport_for_retry()
                        continue

                    self._decoder = _av_module.CodecContext.create("h264", "r")
                    self._decode_error_count = 0
                    self._packet_count = 0
                    self._h264_packet_format = None
                    self._h264_annexb_config = None
                    self._prefer_opencv_yuv = False

                    self._decode_thread = threading.Thread(
                        target=self._decode_loop,
                        daemon=True,
                        name=f"scrcpy-decode-{self.serial[:8]}",
                    )
                    self._decode_thread.start()

                    self._connected = True
                    app_logger.log(
                        f"[scrcpy] Reconnected to {self.serial} on port {self.local_port}",
                        "INFO",
                    )
                    return

                except Exception as e:
                    app_logger.log(
                        f"[scrcpy] Reconnect attempt {attempt} failed for "
                        f"{self.serial}: {e}",
                        "WARNING",
                    )
                    self._reset_transport_for_retry()

            self._connected = False
            self._latest_frame = None
            app_logger.log(
                f"[scrcpy] Recovery exhausted for {self.serial} — "
                f"backend disconnected",
                "ERROR",
            )
        finally:
            self._reconnecting = False
