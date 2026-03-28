import cv2
import mediapipe as mp
import ctypes
import win32api
import win32con
from pathlib import Path
from mediapipe.tasks import python
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

SCREEN_WIDTH  = ctypes.windll.user32.GetSystemMetrics(0)
SCREEN_HEIGHT = ctypes.windll.user32.GetSystemMetrics(1)

# ---------------------------------------------------------------------------
# Model path
# ---------------------------------------------------------------------------
model_path = str((Path(__file__).parent / "hand_landmarker.task").resolve())

# ---------------------------------------------------------------------------
# Skeleton connections
# ---------------------------------------------------------------------------
CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),
    (9,13),(13,14),(14,15),(15,16),
    (13,17),(0,17),(17,18),(18,19),(19,20),
]

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------
CAM_W, CAM_H = 640, 480
Z_SCALE = 3.0
Y_SHIFT = 0.3   # shift the whole view down (increase if screen still too high)

# Hit remapping — use corner calibration (press c) to set these automatically
HIT_X_MIN = 0.2
HIT_X_MAX = 0.8
HIT_Y_MIN = 0.2
HIT_Y_MAX = 0.8

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
latest_frame       = None
calibMidFingerDist = 0.0
hit_point          = None
debug_str          = ""

calib_mode   = False
calib_corner = 0
calib_hits   = {}
CORNER_NAMES = ["TOP-LEFT", "TOP-RIGHT", "BOTTOM-LEFT", "BOTTOM-RIGHT"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def lm_x(lm):
    """Flip x to match the mirrored camera feed."""
    return 1.0 - lm.x

def hit_to_screen(hit_x, hit_y):
    sx = (hit_x - HIT_X_MIN) / (HIT_X_MAX - HIT_X_MIN)
    sy = (hit_y - HIT_Y_MIN) / (HIT_Y_MAX - HIT_Y_MIN)
    sx = max(0.0, min(1.0, sx))
    sy = max(0.0, min(1.0, sy))
    return int(sx * SCREEN_WIDTH), int(sy * SCREEN_HEIGHT)

SMOOTH = 0.5   # EMA smoothing (0=raw/jittery, 1=frozen)
_smooth_hx = 0.5
_smooth_hy = 0.5

def finger_ray_screen_hit(base_lm, tip_lm, z_scale):
    dx = tip_lm.x - base_lm.x
    dy = (tip_lm.y + Y_SHIFT) - (base_lm.y + Y_SHIFT)   # shift cancels in direction
    dz = tip_lm.z - base_lm.z

    if dz > -0.01:
        return None

    t = -z_scale / dz
    t = min(t, 2.0)

    hit_x = base_lm.x + t * dx
    hit_y = (base_lm.y + Y_SHIFT) + t * dy   # shift the origin down

    return hit_x, hit_y

# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------
def callback(result, mp_image, timestamp_ms):
    global latest_frame, calibMidFingerDist, hit_point, debug_str

    frame = mp_image.numpy_view().copy()
    h, w, _ = frame.shape

    if result.hand_landmarks:
        hand = result.hand_landmarks[0]

        # --- Depth calibration ---
        MIDDLE_SEGMENTS = [(12,11),(11,10),(10,9),(9,0)]

        def finger_len():
            total = 0.0
            for a, b in MIDDLE_SEGMENTS:
                dx = hand[a].x - hand[b].x
                dy = hand[a].y - hand[b].y
                total += (dx*dx + dy*dy) ** 0.5
            return total

        midFingerDist = finger_len()
        if calibMidFingerDist == 0.0:
            calibMidFingerDist = midFingerDist
        depth_ratio = midFingerDist / calibMidFingerDist if calibMidFingerDist else 1.0

        # --- Ray-screen intersection ---
        hit = finger_ray_screen_hit(hand[5], hand[8], Z_SCALE)

        # Smooth the hit point to reduce jitter
        global _smooth_hx, _smooth_hy
        if hit:
            _smooth_hx = SMOOTH * _smooth_hx + (1 - SMOOTH) * hit[0]
            _smooth_hy = SMOOTH * _smooth_hy + (1 - SMOOTH) * hit[1]
            hit = (_smooth_hx, _smooth_hy)

        hit_point = hit

        # --- Move mouse ---
        if hit:
            mx, my = hit_to_screen(hit[0], hit[1])
            win32api.SetCursorPos((mx, my))

        # --- Debug ---
        base_lm = hand[5]
        tip_lm  = hand[8]
        debug_str = f"base.z={base_lm.z:.4f}  tip.z={tip_lm.z:.4f}  dz={tip_lm.z - base_lm.z:.4f}"

        # --- Draw skeleton ---
        for a, b in CONNECTIONS:
            ax, ay = int(hand[a].x * w), int(hand[a].y * h)
            bx, by = int(hand[b].x * w), int(hand[b].y * h)
            cv2.line(frame, (ax, ay), (bx, by), (200, 200, 200), 1)

        # --- Draw landmarks ---
        for i, lm in enumerate(hand):
            cx, cy = int(lm.x * w), int(lm.y * h)
            cv2.circle(frame, (cx, cy), 4, (255, 255, 255), -1)
            cv2.putText(frame, str(i), (cx + 4, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)

        # --- Draw ray line ---
        base = hand[5]
        tip  = hand[8]
        ext  = 3.0
        ray_ex = int((base.x + ext * (tip.x - base.x)) * w)
        ray_ey = int((base.y + ext * (tip.y - base.y)) * h)
        cv2.line(frame,
                 (int(base.x * w), int(base.y * h)),
                 (ray_ex, ray_ey),
                 (0, 180, 255), 1)

        # --- Draw hit point ---
        if hit:
            hx = max(0, min(w-1, int(hit[0] * w)))
            hy = max(0, min(h-1, int(hit[1] * h)))
            cv2.drawMarker(frame, (hx, hy), (0, 255, 0), cv2.MARKER_CROSS, 20, 2)

        # --- HUD ---
        cv2.rectangle(frame, (0, 0), (w, 80), (0, 0, 0), -1)
        cv2.putText(frame,
                    f"calib={calibMidFingerDist:.4f}  curr={midFingerDist:.4f}  depth_ratio={depth_ratio:.2f}",
                    (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
        if hit:
            sx, sy = hit_to_screen(hit[0], hit[1])
            hit_str = f"hit=({hit[0]:.3f},{hit[1]:.3f})  screen=({sx},{sy})"
        else:
            hit_str = "hit=None (finger parallel to screen)"
        cv2.putText(frame,
                    f"Z_SCALE={Z_SCALE:.1f} (+/-)   {hit_str}",
                    (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)

        if calib_mode:
            corner_name = CORNER_NAMES[calib_corner] if calib_corner < 4 else "DONE"
            cv2.putText(frame,
                        f"CALIB: point at {corner_name}, press C to record",
                        (8, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    else:
        hit_point = None

    latest_frame = frame

# ---------------------------------------------------------------------------
# MediaPipe setup
# ---------------------------------------------------------------------------
options = HandLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path=model_path),
    running_mode=RunningMode.LIVE_STREAM,
    result_callback=callback,
    num_hands=1,
)
landmarker = HandLandmarker.create_from_options(options)

# ---------------------------------------------------------------------------
# Webcam loop
# ---------------------------------------------------------------------------
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_W)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
ts_freq = cv2.getTickFrequency()

print("Hand skeleton + ray pointer running.")
print("  +/- →  tune Z_SCALE (tilt sensitivity)")
print("  c   →  corner calibration")
print("  r   →  reset depth calibration")
print("  ESC →  quit")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)

    mp_image  = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
    timestamp = int(cv2.getTickCount() / ts_freq * 1000)
    landmarker.detect_async(mp_image, timestamp)

    display = latest_frame if latest_frame is not None else frame
    cv2.imshow("Hand Skeleton", display)

    if debug_str:
        print(debug_str)

    key = cv2.waitKey(1) & 0xFF
    if key == 27:
        break
    elif key == ord('+') or key == ord('='):
        Z_SCALE = round(Z_SCALE + 0.5, 1)
        print(f"Z_SCALE → {Z_SCALE}")
    elif key == ord('-'):
        Z_SCALE = round(max(0.5, Z_SCALE - 0.5), 1)
        print(f"Z_SCALE → {Z_SCALE}")
    elif key == ord('r'):
        calibMidFingerDist = 0.0
        print("Depth calibration reset")
    elif key == ord('c'):
        if not calib_mode:
            calib_mode   = True
            calib_corner = 0
            calib_hits   = {}
            print(f"Corner calibration started. Point at {CORNER_NAMES[0]} and press C.")
        elif hit_point and calib_corner < 4:
            calib_hits[calib_corner] = hit_point
            print(f"  Recorded {CORNER_NAMES[calib_corner]}: {hit_point}")
            calib_corner += 1
            if calib_corner < 4:
                print(f"  Now point at {CORNER_NAMES[calib_corner]} and press C.")
            else:
                xs = [calib_hits[i][0] for i in range(4)]
                ys = [calib_hits[i][1] for i in range(4)]
                # Update globals directly
                HIT_X_MIN = min(xs)
                HIT_X_MAX = max(xs)
                HIT_Y_MIN = min(ys)
                HIT_Y_MAX = max(ys)
                # Patch hit_to_screen's closure by redefining it
                def hit_to_screen(hit_x, hit_y,
                                  xmin=HIT_X_MIN, xmax=HIT_X_MAX,
                                  ymin=HIT_Y_MIN, ymax=HIT_Y_MAX):
                    sx = (hit_x - xmin) / (xmax - xmin)
                    sy = (hit_y - ymin) / (ymax - ymin)
                    sx = max(0.0, min(1.0, sx))
                    sy = max(0.0, min(1.0, sy))
                    return int(sx * SCREEN_WIDTH), int(sy * SCREEN_HEIGHT)
                calib_mode = False
                print("Calibration done!")
                print(f"  HIT_X_MIN={HIT_X_MIN:.3f}  HIT_X_MAX={HIT_X_MAX:.3f}")
                print(f"  HIT_Y_MIN={HIT_Y_MIN:.3f}  HIT_Y_MAX={HIT_Y_MAX:.3f}")
                print("  Copy these into the config at the top to make permanent.")

cap.release()
cv2.destroyAllWindows()
landmarker.close()