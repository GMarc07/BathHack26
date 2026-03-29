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


# ──────────────────────────────────────────────
# App
# ──────────────────────────────────────────────

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Hand Tracker — Config")
        self.geometry("440x560")
        self.resizable(False, False)

        self.cfg = load_config()
        self._tracker_proc = None

        self._build_ui()

    # ── UI construction ────────────────────────

    def _build_ui(self):
        pad = {"padx": 20, "pady": (6, 0)}

        ctk.CTkLabel(self, text="Hand Tracker Config",
                     font=ctk.CTkFont(size=18, weight="bold")
                     ).pack(pady=(20, 2))

        ctk.CTkLabel(self, text="⚡ = applies live   •   ⟳ = requires restart",
                     text_color="gray55", font=ctk.CTkFont(size=12)
                     ).pack(pady=(0, 12))

        # ── Camera ──────────────────────────────
        self._section("Camera")

        self.camera_var = ctk.IntVar(value=self.cfg["camera_index"])
        self._row("Camera index  ⟳",
                  ctk.CTkOptionMenu(self, values=["0", "1", "2", "3"],
                                    variable=ctk.StringVar(value=str(self.cfg["camera_index"])),
                                    command=lambda v: self.camera_var.set(int(v)),
                                    width=100))

        # ── Screen resolution ────────────────────
        self._section("Screen Resolution  ⚡")

        self.sw_var = ctk.IntVar(value=self.cfg["screen_width"])
        self.sh_var = ctk.IntVar(value=self.cfg["screen_height"])

        res_frame = ctk.CTkFrame(self, fg_color="transparent")
        res_frame.pack(fill="x", **pad)
        ctk.CTkLabel(res_frame, text="Width", width=60).pack(side="left")
        self.sw_entry = ctk.CTkEntry(res_frame, textvariable=self.sw_var, width=80)
        self.sw_entry.pack(side="left", padx=(0, 20))
        ctk.CTkLabel(res_frame, text="Height", width=60).pack(side="left")
        self.sh_entry = ctk.CTkEntry(res_frame, textvariable=self.sh_var, width=80)
        self.sh_entry.pack(side="left")

        # ── Tracking ─────────────────────────────
        self._section("Tracking")

        self.sens_var = ctk.DoubleVar(value=self.cfg["sensitivity"])
        self._slider_row("Sensitivity  ⚡", self.sens_var, 0.5, 4.0)

        self.pinch_var = ctk.DoubleVar(value=self.cfg["pinch_threshold"])
        self._slider_row("Pinch threshold  ⚡", self.pinch_var, 0.05, 0.40)

        self.hands_var = ctk.IntVar(value=self.cfg["num_hands"])
        self._row("Max hands  ⟳",
                  ctk.CTkOptionMenu(self, values=["1", "2"],
                                    variable=ctk.StringVar(value=str(self.cfg["num_hands"])),
                                    command=lambda v: self.hands_var.set(int(v)),
                                    width=100))

        # ── Buttons ──────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(24, 10))

        self.save_btn = ctk.CTkButton(btn_frame, text="💾  Save", width=120,
                                      command=self._on_save)
        self.save_btn.pack(side="left", padx=(0, 10))

        self.launch_btn = ctk.CTkButton(btn_frame, text="▶  Launch tracker",
                                        fg_color="#2a7d4f", hover_color="#1f5c39",
                                        command=self._on_launch)
        self.launch_btn.pack(side="left")

        self.stop_btn = ctk.CTkButton(btn_frame, text="■  Stop tracker",
                                      fg_color="#7d2a2a", hover_color="#5c1f1f",
                                      command=self._on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(10, 0))

        self.status_label = ctk.CTkLabel(self, text="", text_color="gray60",
                                         font=ctk.CTkFont(size=12))
        self.status_label.pack(pady=(0, 10))

    # ── Helpers ────────────────────────────────

    def _section(self, title: str):
        ctk.CTkLabel(self, text=title,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="gray80"
                     ).pack(anchor="w", padx=20, pady=(14, 2))

    def _row(self, label: str, widget):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(4, 0))
        ctk.CTkLabel(row, text=label, width=180, anchor="w").pack(side="left")
        widget.pack(side="left")

    def _slider_row(self, label: str, var: ctk.DoubleVar, lo: float, hi: float):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=(4, 0))

        ctk.CTkLabel(frame, text=label, width=160, anchor="w").pack(side="left")

        val_label = ctk.CTkLabel(frame, text=f"{var.get():.2f}", width=40)
        val_label.pack(side="right")

        def on_slide(v):
            val_label.configure(text=f"{float(v):.2f}")

        ctk.CTkSlider(frame, from_=lo, to=hi, variable=var,
                      command=on_slide, width=160
                      ).pack(side="left", padx=(0, 6))

    # ── Actions ────────────────────────────────

    def _collect(self) -> dict:
        return {
            "camera_index":    self.camera_var.get(),
            "sensitivity":     round(self.sens_var.get(), 3),
            "pinch_threshold": round(self.pinch_var.get(), 3),
            "screen_width":    self.sw_var.get(),
            "screen_height":   self.sh_var.get(),
            "num_hands":       self.hands_var.get(),
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