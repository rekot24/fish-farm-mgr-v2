"""
ui/device_settings_dialog.py

Per-device settings dialog. Opened from the Settings button on each device card.
Nickname and Account are merged into one "Nickname / Acct" field.
ADB serial is displayed read-only using direct widget insert.

USB port reset section: a free-text "PnP Instance ID (USB reset)" field (blank = skip
USB reset for this device) plus a Detect button that looks the ID up from the ADB
serial. The field stays the source of truth; Detect only fills it in. The lookup runs
on a background thread (PowerShell startup takes a second or two) and is polled from
the UI thread, so the dialog never freezes.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from dataclasses import replace

from config.devices import DeviceConfig
from tools import usb_pnp
from tools.usb_pnp import LookupStatus

# --- UI layout constants (pixel sizes / widths / timings; see CLAUDE.md instruction 5) ---
PNP_ENTRY_WIDTH = 34          # chars; InstanceIds are ~40 chars, the entry scrolls
DETECT_BTN_WIDTH = 8          # chars
NOTE_WRAP_PX = 420            # wrap width for the explanatory notes / status line
DETECT_POLL_MS = 100          # how often the UI thread checks for the lookup result
COLOR_NOTE = "#6b7280"        # grey — explanatory text
COLOR_OK = "#15803d"          # green — found
COLOR_WARN = "#b45309"        # amber — not found / ambiguous
COLOR_ERROR = "#b91c1c"       # red — error / invalid input


class DeviceSettingsDialog(tk.Toplevel):

    def __init__(self, parent, cfg: DeviceConfig):
        super().__init__(parent)
        self._cfg = cfg
        self.result: DeviceConfig | None = None
        self._detect_result: usb_pnp.LookupResult | None = None

        self.title(f"Device settings — {cfg.nickname or cfg.serial[:8]}")
        self.resizable(False, False)
        self.grab_set()

        self._build()
        self._load(cfg)

        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{px}+{py}")

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        # Identity
        ttk.Label(frame, text="Identity", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self._nickname_var = self._row(frame, 1, "Nickname / Acct")
        self._model_var    = self._row(frame, 2, "Model")

        # ADB serial — read-only, populated via direct insert
        ttk.Label(frame, text="ADB serial").grid(
            row=3, column=0, sticky="w", padx=(0, 12), pady=2)
        self._serial_entry = ttk.Entry(frame, width=28, state="normal")
        self._serial_entry.grid(row=3, column=1, sticky="ew", pady=2)

        ttk.Separator(frame, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=10)

        # Timer intervals
        ttk.Label(frame, text="Timer intervals (seconds)", font=("", 10, "bold")).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self._auto_farm_var  = self._row(frame, 6, "Auto-farm interval")
        self._end_run_var    = self._row(frame, 7, "End-run interval")
        self._stay_awake_var = self._row(frame, 8, "Stay-awake interval")

        ttk.Separator(frame, orient="horizontal").grid(
            row=9, column=0, columnspan=2, sticky="ew", pady=10)

        # USB port reset (Level 4 recovery). Blank field = skip for this device.
        ttk.Label(frame, text="USB port reset (Windows)", font=("", 10, "bold")).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(frame, text="PnP Instance ID (USB reset)").grid(
            row=11, column=0, sticky="w", padx=(0, 12), pady=2)
        pnp_row = ttk.Frame(frame)
        pnp_row.grid(row=11, column=1, sticky="ew", pady=2)
        self._pnp_var = tk.StringVar()
        ttk.Entry(pnp_row, textvariable=self._pnp_var, width=PNP_ENTRY_WIDTH).pack(
            side="left", fill="x", expand=True)
        self._detect_btn = ttk.Button(
            pnp_row, text="Detect", width=DETECT_BTN_WIDTH, command=self._on_detect)
        self._detect_btn.pack(side="left", padx=(6, 0))

        self._pnp_status = ttk.Label(
            frame, text="", font=("", 9), wraplength=NOTE_WRAP_PX, justify="left")
        self._pnp_status.grid(row=12, column=0, columnspan=2, sticky="w", pady=(2, 0))

        ttk.Label(
            frame,
            text="Windows USB device ID used for the last-resort USB port reset. Click "
                 "Detect with the phone plugged in, or run in PowerShell:\n"
                 "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like "
                 f"'USB\\VID_*\\{self._cfg.serial}' }} | Select-Object FriendlyName, "
                 "InstanceId\n"
                 "Leave blank to skip USB reset for this device. Requires the app to "
                 "run as administrator.",
            foreground=COLOR_NOTE, font=("", 9), justify="left", wraplength=NOTE_WRAP_PX,
        ).grid(row=13, column=0, columnspan=2, sticky="w", pady=(2, 0))

        if not usb_pnp.is_windows():
            self._detect_btn.config(state="disabled")
            self._set_status("USB reset is only supported on Windows.", COLOR_NOTE)

        ttk.Label(
            frame,
            text="Tap coordinates are set automatically via template matching.\n"
                 "Use the Capture tab to assign detector images.",
            foreground=COLOR_NOTE, font=("", 9), justify="left"
        ).grid(row=14, column=0, columnspan=2, sticky="w", pady=(10, 0))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=15, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side="right")

        frame.columnconfigure(1, weight=1)

    def _row(self, parent, row: int, label: str) -> tk.StringVar:
        var = tk.StringVar()
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 12), pady=2)
        ttk.Entry(parent, textvariable=var, width=28).grid(
            row=row, column=1, sticky="ew", pady=2)
        return var

    def _load(self, cfg: DeviceConfig) -> None:
        self._nickname_var.set(cfg.nickname or "")
        self._model_var.set(cfg.model or "")
        self._auto_farm_var.set(str(cfg.auto_farm_interval_s))
        self._end_run_var.set(str(cfg.end_run_interval_s))
        self._stay_awake_var.set(str(cfg.stay_awake_interval_s))
        self._pnp_var.set(cfg.pnp_instance_id or "")
        # Insert serial directly then lock — bypasses readonly StringVar issue
        self._serial_entry.insert(0, cfg.serial)
        self._serial_entry.config(state="readonly")

    def _set_status(self, text: str, color: str) -> None:
        """Show a one-line status under the PnP Instance ID field."""
        self._pnp_status.config(text=text, foreground=color)

    def _on_detect(self) -> None:
        """
        Look up this phone's PnP InstanceId from its ADB serial and fill the field.
        The PowerShell lookup takes a second or two, so it runs on a background thread
        and the UI thread polls for the result — the dialog never freezes. Only fills
        the field; nothing is saved until the user clicks Save.
        """
        self._detect_btn.config(state="disabled")
        self._set_status("Detecting… (takes a few seconds)", COLOR_NOTE)
        self._detect_result = None
        threading.Thread(target=self._detect_worker, name="pnp-detect", daemon=True).start()
        self.after(DETECT_POLL_MS, self._poll_detect)

    def _detect_worker(self) -> None:
        """Background thread: run the lookup and publish the result for the UI thread."""
        self._detect_result = usb_pnp.find_instance_id(self._cfg.serial)

    def _poll_detect(self) -> None:
        """UI thread: wait for the lookup, then update the field, status line and button."""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return  # dialog was closed while the lookup was running
        result = self._detect_result
        if result is None:
            self.after(DETECT_POLL_MS, self._poll_detect)
            return

        self._detect_btn.config(state="normal")
        if result.status is LookupStatus.FOUND:
            self._pnp_var.set(result.instance_id)
            self._set_status(f"Found {result.instance_id} — click Save to keep it.", COLOR_OK)
        elif result.status in (LookupStatus.NOT_FOUND, LookupStatus.AMBIGUOUS):
            self._set_status(result.message, COLOR_WARN)
        else:
            self._set_status(f"Detect failed: {result.message}", COLOR_ERROR)

    def _save(self) -> None:
        def _float(v: tk.StringVar, default: float) -> float:
            try: return float(v.get()) if v.get().strip() else default
            except ValueError: return default

        pnp_id = self._pnp_var.get().strip()
        if pnp_id and not usb_pnp.is_valid_instance_id(pnp_id):
            self._set_status(
                "Invalid PnP Instance ID — use Detect, or clear the field to skip USB reset.",
                COLOR_ERROR)
            return

        nickname = self._nickname_var.get().strip()
        self.result = replace(
            self._cfg,
            nickname=nickname,
            model=self._model_var.get().strip(),
            account=nickname,   # keep account in sync with nickname
            auto_farm_interval_s=_float(self._auto_farm_var, self._cfg.auto_farm_interval_s),
            end_run_interval_s=_float(self._end_run_var, self._cfg.end_run_interval_s),
            stay_awake_interval_s=_float(self._stay_awake_var, self._cfg.stay_awake_interval_s),
            pnp_instance_id=pnp_id,
        )
        self.destroy()
