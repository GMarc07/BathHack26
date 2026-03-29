import customtkinter as ctk
import json
import subprocess
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "tracker_config.json"
TRACKER_FILE = Path(__file__).parent / "skeletonTracking.py"

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


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Hand Tracker — Config")
        self.geometry("480x600")
        self.resizable(False, False)

        self.cfg = load_config()
        self._tracker_proc = None

        self._build_ui()

    # ──────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────

    def _build_ui(self):
        title = ctk.CTkLabel(self, text="Hand Tracker Config",
                             font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=(20, 4))

        subtitle = ctk.CTkLabel(self, text="⚡ = applies live   •   ⟳ = requires restart",
                                text_color="gray65", font=ctk.CTkFont(size=12))
        subtitle.pack(pady=(0, 16))

        # Main form container
        self.form = ctk.CTkFrame(self, fg_color="transparent")
        self.form.pack(fill="both", expand=True, padx=20)

        row = 0

        # ── Camera ──────────────────────────────
        self._section("Camera", row); row += 1

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

        self.status_label = ctk.CTkLabel(self, text="", text_color="gray60",
                                         font=ctk.CTkFont(size=12))
        self.status_label.pack(pady=(0, 10))

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

    # ──────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────

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
        cfg = self._collect()
        save_config(cfg)
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
