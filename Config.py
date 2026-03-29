import customtkinter as ctk
import json
import subprocess
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "tracker_config.json"
TRACKER_FILE = Path(__file__).parent / "skeletonTracking.py"

sys.path.insert(0, str(Path(__file__).parent))
import GestureEngine as ge

DEFAULTS = {
    "camera_index": 1,
    "sensitivity": 1.6,
    "pinch_threshold": 0.15,
    "screen_width": 1920,
    "screen_height": 1080,
    "num_hands": 1,
    "mouse_mode": "Fist"
}

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            return {**DEFAULTS, **data}
        except Exception:
            pass
    return dict(DEFAULTS)

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

RECORD_COUNTDOWN = 3
LABEL_W = 200   # fixed label column width throughout settings tab


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Hand Tracker — Config")
        self.geometry("520x660")
        self.resizable(False, False)

        self.cfg = load_config()
        self._tracker_proc = None
        self._build_ui()

    # ─────────────────────────────────────────────────────────────
    # Shell
    # ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=("#1a1a2e", "#0d0d1a"), corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(
            header, text="✋  Hand Tracker",
            font=ctk.CTkFont(size=20, weight="bold"), text_color="#4a9eff"
        ).pack(side="left", padx=20, pady=14)
        ctk.CTkLabel(
            header, text="⚡ live   ⟳ needs restart",
            text_color="gray55", font=ctk.CTkFont(size=11)
        ).pack(side="right", padx=16, pady=14)

        # Tabs
        self.tabs = ctk.CTkTabview(self, width=500, height=530)
        self.tabs.pack(padx=10, pady=(8, 0), fill="both", expand=True)
        self.tabs.add("⚙  Settings")
        self.tabs.add("🖐  Gestures")
        self._build_settings_tab(self.tabs.tab("⚙  Settings"))
        self._build_gestures_tab(self.tabs.tab("🖐  Gestures"))

        # Status
        self.status_label = ctk.CTkLabel(
            self, text="", text_color="gray60", font=ctk.CTkFont(size=12)
        )
        self.status_label.pack(pady=(6, 0))

        # Bottom buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=(4, 14))

        self.save_btn = ctk.CTkButton(
            btn_frame, text="💾  Save", width=130, command=self._on_save
        )
        self.save_btn.pack(side="left", padx=8)

        self.launch_btn = ctk.CTkButton(
            btn_frame, text="▶  Launch Tracker",
            fg_color="#2a7d4f", hover_color="#1f5c39",
            width=150, command=self._on_launch
        )
        self.launch_btn.pack(side="left", padx=8)

        self.stop_btn = ctk.CTkButton(
            btn_frame, text="■  Stop",
            fg_color="#7d2a2a", hover_color="#5c1f1f",
            width=100, command=self._on_stop, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=8)

    # ─────────────────────────────────────────────────────────────
    # Settings tab
    # ─────────────────────────────────────────────────────────────

    def _build_settings_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # ── Camera ──────────────────────────────────────────────
        self._section_heading(scroll, "Camera")

        self.camera_var = ctk.StringVar(value=str(self.cfg["camera_index"]))
        row = self._make_row(scroll, "Camera index  ⟳")
        ctk.CTkOptionMenu(
            row, values=["0", "1", "2", "3"],
            variable=self.camera_var, width=120
        ).pack(side="left")

        # ── Screen Resolution ────────────────────────────────────
        self._section_heading(scroll, "Screen Resolution  ⚡")

        self.sw_var = ctk.IntVar(value=self.cfg["screen_width"])
        row = self._make_row(scroll, "Width")
        ctk.CTkEntry(row, textvariable=self.sw_var, width=120).pack(side="left")

        self.sh_var = ctk.IntVar(value=self.cfg["screen_height"])
        row = self._make_row(scroll, "Height")
        ctk.CTkEntry(row, textvariable=self.sh_var, width=120).pack(side="left")

        # ── Tracking ─────────────────────────────────────────────
        self._section_heading(scroll, "Tracking")

        self.sens_var = ctk.DoubleVar(value=self.cfg["sensitivity"])
        self._make_slider_row(scroll, "Sensitivity  ⚡", self.sens_var, 0.5, 4.0)

        self.pinch_var = ctk.DoubleVar(value=self.cfg["pinch_threshold"])
        self._make_slider_row(scroll, "Pinch threshold  ⚡", self.pinch_var, 0.05, 0.40)

        self.hands_var = ctk.StringVar(value=str(self.cfg["num_hands"]))
        row = self._make_row(scroll, "Max hands  ⟳")
        ctk.CTkOptionMenu(
            row, values=["1", "2"],
            variable=self.hands_var, width=120
        ).pack(side="left")

        self.mouse_var = ctk.StringVar(value=self.cfg["mouse_mode"])
        row = self._make_row(scroll, "Mouse mode")
        ctk.CTkOptionMenu(
            row, values=["Fist", "Point"],
            variable=self.mouse_var, width=120
        ).pack(side="left")

    # ─────────────────────────────────────────────────────────────
    # Gestures tab
    # ─────────────────────────────────────────────────────────────

    def _build_gestures_tab(self, parent):
        # Record card
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.pack(fill="x", padx=8, pady=(8, 6))

        ctk.CTkLabel(
            card, text="Record New Gesture",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=14, pady=(10, 6))

        # Name
        r = ctk.CTkFrame(card, fg_color="transparent")
        r.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(r, text="Name", width=72, anchor="w").pack(side="left")
        self.gesture_name_var = ctk.StringVar()
        ctk.CTkEntry(
            r, textvariable=self.gesture_name_var,
            placeholder_text="e.g. Peace Sign", width=210
        ).pack(side="left", padx=(6, 0))

        # Action
        r = ctk.CTkFrame(card, fg_color="transparent")
        r.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(r, text="Action", width=72, anchor="w").pack(side="left")
        self.action_var = ctk.StringVar(value=ge.ACTIONS[0])
        self.action_menu = ctk.CTkOptionMenu(
            r, values=ge.ACTIONS, variable=self.action_var,
            command=self._on_action_change, width=190
        )
        self.action_menu.pack(side="left", padx=(6, 0))

        # Custom key (hidden by default)
        self.key_row = ctk.CTkFrame(card, fg_color="transparent")
        ctk.CTkLabel(self.key_row, text="Key", width=72, anchor="w").pack(side="left")
        self.key_var = ctk.StringVar()
        ctk.CTkEntry(
            self.key_row, textvariable=self.key_var,
            placeholder_text="e.g. ctrl+c or space", width=190
        ).pack(side="left", padx=(6, 0))

        # Tolerance slider
        r = ctk.CTkFrame(card, fg_color="transparent")
        r.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(r, text="Tolerance", width=72, anchor="w").pack(side="left")
        self.thresh_var = ctk.DoubleVar(value=0.20)
        thresh_val = ctk.CTkLabel(r, text="0.20", width=40)
        thresh_val.pack(side="right", padx=(0, 8))
        ctk.CTkSlider(
            r, from_=0.05, to=0.40, variable=self.thresh_var, width=170,
            command=lambda v: thresh_val.configure(text=f"{float(v):.2f}")
        ).pack(side="left", padx=(6, 0))

        # Record button + status
        r = ctk.CTkFrame(card, fg_color="transparent")
        r.pack(fill="x", padx=14, pady=(6, 12))
        self.record_btn = ctk.CTkButton(
            r, text="✋  Record Gesture",
            fg_color="#4a6fa5", hover_color="#3a5a8a",
            command=self._on_record_start, width=160
        )
        self.record_btn.pack(side="left")
        self.record_status = ctk.CTkLabel(
            r, text="", text_color="gray60",
            font=ctk.CTkFont(size=12), width=230
        )
        self.record_status.pack(side="left", padx=(10, 0))

        # Saved gestures list
        ctk.CTkLabel(
            parent, text="Saved Gestures",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="gray80"
        ).pack(anchor="w", padx=14, pady=(4, 2))

        self.gesture_scroll = ctk.CTkScrollableFrame(parent, height=180)
        self.gesture_scroll.pack(fill="x", padx=8, pady=(0, 8))
        self._refresh_gesture_list()

    # ─────────────────────────────────────────────────────────────
    # Layout helpers
    # ─────────────────────────────────────────────────────────────

    def _section_heading(self, parent, title: str):
        """Blue bold heading + thin separator line."""
        ctk.CTkLabel(
            parent, text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#4a9eff"
        ).pack(anchor="w", padx=12, pady=(14, 2))
        ctk.CTkFrame(parent, height=1, fg_color="gray30").pack(
            fill="x", padx=12, pady=(0, 4)
        )

    def _make_row(self, parent, label: str) -> ctk.CTkFrame:
        """
        Creates a horizontal row frame with a fixed-width label already packed
        on the left. Returns the frame so the caller packs its input widget into it.
        The key rule: the input widget must be created with THIS returned frame
        as its parent — not with `parent` (the scroll container).
        """
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(row, text=label, width=LABEL_W, anchor="w").pack(side="left")
        return row

    def _make_slider_row(self, parent, label: str, var, lo: float, hi: float):
        """Row with label, slider, and live numeric readout — all in one frame."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(row, text=label, width=LABEL_W, anchor="w").pack(side="left")

        val_lbl = ctk.CTkLabel(row, text=f"{var.get():.2f}", width=46, anchor="e")
        val_lbl.pack(side="right")

        ctk.CTkSlider(
            row, from_=lo, to=hi, variable=var, width=160,
            command=lambda v: val_lbl.configure(text=f"{float(v):.2f}")
        ).pack(side="right", padx=(0, 8))

    # ─────────────────────────────────────────────────────────────
    # Gesture helpers
    # ─────────────────────────────────────────────────────────────

    def _on_action_change(self, value):
        if value == "custom_key":
            self.key_row.pack(
                fill="x", padx=14, pady=(0, 4),
                after=self.action_menu.master
            )
        else:
            self.key_row.pack_forget()

    def _refresh_gesture_list(self):
        for w in self.gesture_scroll.winfo_children():
            w.destroy()

        gestures = ge.load_gestures()
        if not gestures:
            ctk.CTkLabel(
                self.gesture_scroll,
                text="No gestures saved yet.", text_color="gray55"
            ).pack(pady=8)
            return

        for g in gestures:
            row = ctk.CTkFrame(self.gesture_scroll)
            row.pack(fill="x", pady=(0, 4))

            info = f"{g['name']}  →  {g['action']}"
            if g.get("key"):
                info += f"  ({g['key']})"
            ctk.CTkLabel(
                row, text=info, anchor="w", font=ctk.CTkFont(size=12)
            ).pack(side="left", padx=(10, 0), pady=6, expand=True, fill="x")

            ctk.CTkLabel(
                row, text=f"±{g.get('threshold', 0.20):.2f}",
                text_color="gray55", font=ctk.CTkFont(size=11), width=42
            ).pack(side="left")

            name = g["name"]
            ctk.CTkButton(
                row, text="✕", width=30, height=26,
                fg_color="#5c1f1f", hover_color="#7d2a2a",
                command=lambda n=name: self._on_delete_gesture(n)
            ).pack(side="right", padx=6, pady=4)

    def _on_delete_gesture(self, name: str):
        ge.delete_gesture(name)
        self._refresh_gesture_list()
        self._flash(f"Deleted '{name}'")

    # ─────────────────────────────────────────────────────────────
    # Record flow
    # ─────────────────────────────────────────────────────────────

    def _on_record_start(self):
        name = self.gesture_name_var.get().strip()
        if not name:
            self._set_record_status("⚠ Enter a gesture name first", "orange")
            return
        action = self.action_var.get()
        key = self.key_var.get().strip() if action == "custom_key" else ""
        ge.request_record(name, action, key)
        self.record_btn.configure(state="disabled")
        self._record_countdown(RECORD_COUNTDOWN, name)

    def _record_countdown(self, remaining: int, name: str):
        if remaining > 0:
            self._set_record_status(f"Hold your pose…  {remaining}s", "#4a9eff")
            self.after(1000, lambda: self._record_countdown(remaining - 1, name))
        else:
            self._set_record_status("Capturing…", "#4a9eff")
            self._poll_record_result(name, attempts=0)

    def _poll_record_result(self, name: str, attempts: int):
        result = ge.poll_result()
        if result:
            ge.clear_result()
            if result.get("status") == "ok":
                self._set_record_status(f"✓ '{name}' saved!", "#2a9d4f")
                self._refresh_gesture_list()
            else:
                reason = result.get("reason", "unknown error")
                self._set_record_status(f"✗ Failed: {reason}", "#c0392b")
            self.record_btn.configure(state="normal")
            self.after(3000, lambda: self._set_record_status(""))
        elif attempts < 30:
            self.after(100, lambda: self._poll_record_result(name, attempts + 1))
        else:
            ge.fail_record("tracker not responding")
            ge.clear_result()
            self._set_record_status("✗ No response — is tracker running?", "#c0392b")
            self.record_btn.configure(state="normal")
            self.after(4000, lambda: self._set_record_status(""))

    def _set_record_status(self, msg: str, color: str = "gray60"):
        self.record_status.configure(text=msg, text_color=color)

    # ─────────────────────────────────────────────────────────────
    # Config collect / save / launch / stop
    # ─────────────────────────────────────────────────────────────

    def _collect(self) -> dict:
        return {
            "camera_index": int(self.camera_var.get()),
            "sensitivity": round(self.sens_var.get(), 3),
            "pinch_threshold": round(self.pinch_var.get(), 3),
            "screen_width": self.sw_var.get(),
            "screen_height": self.sh_var.get(),
            "num_hands": int(self.hands_var.get()),
            "mouse_mode": self.mouse_var.get(),
        }

    def _on_save(self):
        save_config(self._collect())
        self._flash("✓ Config saved")

    def _on_launch(self):
        if self._tracker_proc and self._tracker_proc.poll() is None:
            self._flash("Tracker is already running.")
            return
        self._on_save()
        self._tracker_proc = subprocess.Popen(
            [sys.executable, str(TRACKER_FILE)],
            cwd=str(TRACKER_FILE.parent),
        )
        self.launch_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._flash("▶ Tracker launched")
        self._poll_proc()

    def _on_stop(self):
        if self._tracker_proc:
            self._tracker_proc.terminate()
        self.launch_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._flash("■ Tracker stopped")

    def _poll_proc(self):
        if self._tracker_proc and self._tracker_proc.poll() is not None:
            self.launch_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self._flash("Tracker exited")
        else:
            self.after(1000, self._poll_proc)

    def _flash(self, msg: str):
        self.status_label.configure(text=msg)
        self.after(3000, lambda: self.status_label.configure(text=""))


if __name__ == "__main__":
    app = App()
    app.mainloop()
