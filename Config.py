import customtkinter as ctk
import json
import subprocess
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "tracker_config.json"
TRACKER_FILE = Path(__file__).parent / "skeletonTracking.py"

# Import gesture engine from same directory
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

RECORD_COUNTDOWN = 3   # seconds the user has to hold their pose


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Hand Tracker — Config")
        self.geometry("480x600")
        self.resizable(False, False)

        self.cfg = load_config()
        self._tracker_proc = None
        self._record_polling = False   # True while waiting for tracker result

        self._build_ui()

    # ──────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────

    def _build_ui(self):

        title = ctk.CTkLabel(self, text="Hand Tracker Config",
                             font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=(20, 4))
    
        self.tabs = ctk.CTkTabview(self, width=460, height=520)
        self.tabs.pack(padx=10, pady=(0, 6), fill="both", expand=True)

        self.tabs.add("Settings")
        self.tabs.add("Gestures")

        # Main form container
        self.form = ctk.CTkFrame(self, fg_color="transparent")
        self.form.pack(fill="both", expand=True, padx=20)

        self._build_settings_tab(self.tabs.tab("Settings"))
        self._build_gestures_tab(self.tabs.tab("Gestures"))

        subtitle = ctk.CTkLabel(self, text="⚡ = applies live   •   ⟳ = requires restart",
                                text_color="gray65", font=ctk.CTkFont(size=12))
        subtitle.pack(pady=(0, 16))



        row = 0

        # ── Camera ──────────────────────────────
        self._section("Camera", row); row += 1

        # ── Global status ──
        self.status_label = ctk.CTkLabel(self, text="", text_color="gray60",
                                         font=ctk.CTkFont(size=12))
        self.status_label.pack(pady=(0, 8))

    # ── Settings tab ──────────────────────────

    def _build_settings_tab(self, parent):
        row = 0
        pad = {"padx": 20, "pady": (6, 0)}

        ctk.CTkLabel(parent, text="⚡ = applies live   •   ⟳ = requires restart",
                     text_color="gray55", font=ctk.CTkFont(size=12)
                     ).pack(pady=(8, 6))

        self._section("Camera", row)
        self.camera_var = ctk.IntVar(value=self.cfg["camera_index"])
        cam_menu = ctk.CTkOptionMenu(self.form, values=["0", "1", "2", "3"],
                                     variable=ctk.StringVar(value=str(self.cfg["camera_index"])),
                                     command=lambda v: self.camera_var.set(int(v)),
                                     width=100)
        self._row("Camera index  ⟳", cam_menu, row); row += 1

        # ── Screen Resolution ───────────────────
        self._section("Screen Resolution  ⚡", row); row += 1

        self.sw_var = ctk.IntVar(value=self.cfg["screen_width"])
        self.sh_var = ctk.IntVar(value=self.cfg["screen_height"])

        sw_entry = ctk.CTkEntry(self.form, textvariable=self.sw_var, width=80)
        sh_entry = ctk.CTkEntry(self.form, textvariable=self.sh_var, width=80)

        self._row("Width", sw_entry, row); row += 1
        self._row("Height", sh_entry, row); row += 1

        # ── Tracking ─────────────────────────────
        self._section("Tracking", row); row += 1

        self.sens_var = ctk.DoubleVar(value=self.cfg["sensitivity"])
        self._slider_row("Sensitivity  ⚡", self.sens_var, 0.5, 4.0, row); row += 1

        self.pinch_var = ctk.DoubleVar(value=self.cfg["pinch_threshold"])
        self._slider_row("Pinch threshold  ⚡", self.pinch_var, 0.05, 0.40, row); row += 1

        self.hands_var = ctk.IntVar(value=self.cfg["num_hands"])
        hands_menu = ctk.CTkOptionMenu(self.form, values=["1", "2"],
                                       variable=ctk.StringVar(value=str(self.cfg["num_hands"])),
                                       command=lambda v: self.hands_var.set(int(v)),
                                       width=100)
        self._row("Max hands  ⟳", hands_menu, row); row += 1

        self.mouse_var = ctk.StringVar(value=self.cfg["mouse_mode"])
        mouse_menu = ctk.CTkOptionMenu(self.form, values=["Fist", "Point"],
                                       variable=self.mouse_var,
                                       command=lambda v: self.mouse_var.set(v),
                                       width=100)
        self._row("Mouse mode", mouse_menu, row); row += 1

        # ── Buttons ──────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=20)

        self.save_btn = ctk.CTkButton(btn_frame, text="💾  Save", width=120,
                                      command=self._on_save)
        self.save_btn.grid(row=0, column=0, padx=10)

        self.launch_btn = ctk.CTkButton(btn_frame, text="▶  Launch tracker",
                                        fg_color="#2a7d4f", hover_color="#1f5c39",
                                        command=self._on_launch)
        self.launch_btn.grid(row=0, column=1, padx=10)

        self.stop_btn = ctk.CTkButton(btn_frame, text="■  Stop tracker",
                                      fg_color="#7d2a2a", hover_color="#5c1f1f",
                                      command=self._on_stop, state="disabled")
        self.stop_btn.grid(row=0, column=2, padx=10)

    # ── Gestures tab ──────────────────────────

    def _build_gestures_tab(self, parent):
        # ── Record new gesture ──
        record_card = ctk.CTkFrame(parent)
        record_card.pack(fill="x", padx=12, pady=(12, 6))

        ctk.CTkLabel(record_card, text="Record New Gesture",
                     font=ctk.CTkFont(size=13, weight="bold")
                     ).pack(anchor="w", padx=12, pady=(10, 4))

        # Name row
        name_row = ctk.CTkFrame(record_card, fg_color="transparent")
        name_row.pack(fill="x", padx=12, pady=(2, 0))
        ctk.CTkLabel(name_row, text="Name", width=60, anchor="w").pack(side="left")
        self.gesture_name_var = ctk.StringVar()
        ctk.CTkEntry(name_row, textvariable=self.gesture_name_var,
                     placeholder_text="e.g. Peace Sign",
                     width=200).pack(side="left", padx=(6, 0))

        # Action row
        action_row = ctk.CTkFrame(record_card, fg_color="transparent")
        action_row.pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkLabel(action_row, text="Action", width=60, anchor="w").pack(side="left")
        self.action_var = ctk.StringVar(value=ge.ACTIONS[0])
        self.action_menu = ctk.CTkOptionMenu(
            action_row, values=ge.ACTIONS,
            variable=self.action_var,
            command=self._on_action_change,
            width=160)
        self.action_menu.pack(side="left", padx=(6, 0))

        # Custom key row (shown only for custom_key)
        self.key_row = ctk.CTkFrame(record_card, fg_color="transparent")
        self.key_row.pack(fill="x", padx=12, pady=(4, 0))
        ctk.CTkLabel(self.key_row, text="Key", width=60, anchor="w").pack(side="left")
        self.key_var = ctk.StringVar()
        ctk.CTkEntry(self.key_row, textvariable=self.key_var,
                     placeholder_text="e.g. ctrl+c or space",
                     width=160).pack(side="left", padx=(6, 0))
        self.key_row.pack_forget()   # hidden by default

        # Threshold row
        thresh_row = ctk.CTkFrame(record_card, fg_color="transparent")
        thresh_row.pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkLabel(thresh_row, text="Tolerance", width=60, anchor="w").pack(side="left")
        self.thresh_var = ctk.DoubleVar(value=0.20)
        thresh_val = ctk.CTkLabel(thresh_row, text="0.20", width=36)
        thresh_val.pack(side="right", padx=(0, 12))
        ctk.CTkSlider(thresh_row, from_=0.05, to=0.40,
                      variable=self.thresh_var, width=160,
                      command=lambda v: thresh_val.configure(text=f"{float(v):.2f}")
                      ).pack(side="left", padx=(6, 0))

        # Record button + countdown
        rec_btn_row = ctk.CTkFrame(record_card, fg_color="transparent")
        rec_btn_row.pack(fill="x", padx=12, pady=(10, 10))
        self.record_btn = ctk.CTkButton(
            rec_btn_row, text="✋  Record Gesture",
            fg_color="#4a6fa5", hover_color="#3a5a8a",
            command=self._on_record_start, width=160)
        self.record_btn.pack(side="left")
        self.record_status = ctk.CTkLabel(
            rec_btn_row, text="", text_color="gray60",
            font=ctk.CTkFont(size=12), width=220)
        self.record_status.pack(side="left", padx=(10, 0))

        # ── Saved gestures list ──
        ctk.CTkLabel(parent, text="Saved Gestures",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="gray80"
                     ).pack(anchor="w", padx=14, pady=(8, 2))

        # Scrollable list frame
        self.gesture_scroll = ctk.CTkScrollableFrame(parent, height=170)
        self.gesture_scroll.pack(fill="x", padx=12, pady=(0, 8))
        self._refresh_gesture_list()

    # ──────────────────────────────────────────────
    # Layout helpers
    # ──────────────────────────────────────────────

    def _section(self, title: str, row: int):
        lbl = ctk.CTkLabel(self.form, text=title,
                           font=ctk.CTkFont(size=14, weight="bold"),
                           text_color="gray80")
        lbl.grid(row=row, column=0, columnspan=3, sticky="w", pady=(12, 4))

    def _row(self, label: str, widget, row: int):
        ctk.CTkLabel(self.form, text=label, anchor="w").grid(
            row=row, column=0, sticky="w", pady=4
        )
        widget.grid(row=row, column=1, sticky="w", pady=4)

    def _slider_row(self, label: str, var, lo, hi, row: int):
        ctk.CTkLabel(self.form, text=label, anchor="w").grid(
            row=row, column=0, sticky="w", pady=4
        )

        slider = ctk.CTkSlider(self.form, from_=lo, to=hi, variable=var, width=160)
        slider.grid(row=row, column=1, sticky="w", pady=4)

        val_label = ctk.CTkLabel(self.form, text=f"{var.get():.2f}")
        val_label.grid(row=row, column=2, sticky="w", padx=10)
        
        def on_slide(v):
            val_label.configure(text=f"{float(v):.2f}")

        slider.configure(command=on_slide)

    # ── Gesture helpers ───────────────────────

    def _on_action_change(self, value):
        if value == "custom_key":
            self.key_row.pack(fill="x", padx=12, pady=(4, 0),
                              after=self.action_menu.master)
        else:
            self.key_row.pack_forget()

    def _refresh_gesture_list(self):
        # Clear existing rows
        for w in self.gesture_scroll.winfo_children():
            w.destroy()

        gestures = ge.load_gestures()
        if not gestures:
            ctk.CTkLabel(self.gesture_scroll,
                         text="No gestures saved yet.",
                         text_color="gray55").pack(pady=8)
            return

        for g in gestures:
            row = ctk.CTkFrame(self.gesture_scroll)
            row.pack(fill="x", pady=(0, 4))

            # Name + action summary
            info = f"{g['name']}  →  {g['action']}"
            if g.get("key"):
                info += f" ({g['key']})"
            ctk.CTkLabel(row, text=info, anchor="w",
                         font=ctk.CTkFont(size=12)
                         ).pack(side="left", padx=(10, 0), pady=6, expand=True, fill="x")

            # Tolerance badge
            ctk.CTkLabel(row,
                         text=f"±{g.get('threshold', 0.20):.2f}",
                         text_color="gray55",
                         font=ctk.CTkFont(size=11), width=42
                         ).pack(side="left")

            # Delete button
            name = g["name"]   # capture for lambda
            ctk.CTkButton(row, text="✕", width=30, height=26,
                          fg_color="#5c1f1f", hover_color="#7d2a2a",
                          command=lambda n=name: self._on_delete_gesture(n)
                          ).pack(side="right", padx=6, pady=4)

    def _on_delete_gesture(self, name: str):
        ge.delete_gesture(name)
        self._refresh_gesture_list()
        self._flash(f"Deleted '{name}'")

    # ── Record flow ───────────────────────────

    def _on_record_start(self):
        name = self.gesture_name_var.get().strip()
        if not name:
            self._set_record_status("⚠ Enter a gesture name first", "orange")
            return

        action = self.action_var.get()
        key    = self.key_var.get().strip() if action == "custom_key" else ""

        # Write the flag for the tracker
        ge.request_record(name, action, key)

        # Start countdown in the UI
        self.record_btn.configure(state="disabled")
        self._record_countdown(RECORD_COUNTDOWN, name)

    def _record_countdown(self, remaining: int, name: str):
        if remaining > 0:
            self._set_record_status(
                f"Hold your pose…  {remaining}s", "#4a9eff")
            self.after(1000, lambda: self._record_countdown(remaining - 1, name))
        else:
            # Countdown finished — now poll for tracker result
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
        elif attempts < 30:   # wait up to ~3 more seconds
            self.after(100, lambda: self._poll_record_result(name, attempts + 1))
        else:
            # Timeout — tracker may not be running
            ge.fail_record("tracker not responding")
            ge.clear_result()
            self._set_record_status("✗ No response — is tracker running?", "#c0392b")
            self.record_btn.configure(state="normal")
            self.after(4000, lambda: self._set_record_status(""))

    def _set_record_status(self, msg: str, color: str = "gray60"):
        self.record_status.configure(text=msg, text_color=color)

    # ── Actions ───────────────────────────────

    def _collect(self) -> dict:
        return {
            "camera_index": self.camera_var.get(),
            "sensitivity": round(self.sens_var.get(), 3),
            "pinch_threshold": round(self.pinch_var.get(), 3),
            "screen_width": self.sw_var.get(),
            "screen_height": self.sh_var.get(),
            "num_hands": self.hands_var.get(),
            "mouse_mode": self.mouse_var.get(),
        }

    def _on_save(self):
        save_config(self._collect())
        self._flash("✓ Saved")

    def _on_launch(self):
        if self._tracker_proc and self._tracker_proc.poll() is None:
            self._flash("Tracker already running.")
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
