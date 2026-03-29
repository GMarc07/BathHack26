import cv2
import mediapipe as mp
from pathlib import Path
from mediapipe.tasks import python
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
import math
import json
import time
import pyautogui
import pynput.keyboard as pynput_kb

pyautogui.FAILSAFE = False
SCREEN_WIDTH, SCREEN_HEIGHT = pyautogui.size()

_pynput_kb_ctrl = pynput_kb.Controller()

def _send_key(combo: str):
    parts = combo.lower().split("+")
    key_map = {
        "ctrl":  pynput_kb.Key.ctrl,
        "cmd":   pynput_kb.Key.cmd,
        "alt":   pynput_kb.Key.alt,
        "shift": pynput_kb.Key.shift,
        "right": pynput_kb.Key.right,
        "left":  pynput_kb.Key.left,
        "up":    pynput_kb.Key.up,
        "down":  pynput_kb.Key.down,
        "space": pynput_kb.Key.space,
        "enter": pynput_kb.Key.enter,
        "esc":   pynput_kb.Key.esc,
        "tab":   pynput_kb.Key.tab,
        "backspace": pynput_kb.Key.backspace,
        "delete": pynput_kb.Key.delete,
        "f5":    pynput_kb.Key.f5,
    }
    resolved = []
    for p in parts:
        if p in key_map:
            resolved.append(key_map[p])
        elif len(p) == 1:
            resolved.append(p)
        else:
            print(f"[key] Unknown key part: {p!r}")
            return
    modifiers = resolved[:-1]
    main_key  = resolved[-1]
    with _pynput_kb_ctrl.pressed(*modifiers):
        _pynput_kb_ctrl.press(main_key)
        _pynput_kb_ctrl.release(main_key)


class OneEuroPoint:
    def __init__(self, alpha=0.2):
        self.alpha = alpha
        self.x = None
        self.y = None

    def update(self, x, y):
        if self.x is None:
            self.x, self.y = x, y
            return x, y
        self.x = self.alpha * x + (1 - self.alpha) * self.x
        self.y = self.alpha * y + (1 - self.alpha) * self.y
        return int(self.x), int(self.y)

_cfg_path = Path(__file__).parent / "tracker_config.json"

def load_config():
    cfg = json.loads(_cfg_path.read_text()) if _cfg_path.exists() else {}
    return {
        "sensitivity":      cfg.get("sensitivity", 1.6),
        "pinch_threshold":  cfg.get("pinch_threshold", 0.15),
        "screen_width":     cfg.get("screen_width", SCREEN_WIDTH),
        "screen_height":    cfg.get("screen_height", SCREEN_HEIGHT),
        "num_hands":        cfg.get("num_hands", 1),
        "camera_index":     cfg.get("camera_index", 0),
        "mouse_mode":       cfg.get("mouse_mode", "Fist"),
    }

_initial        = load_config()
SENSITIVITY     = _initial["sensitivity"]
PINCH_THRESHOLD = _initial["pinch_threshold"]
SCREEN_W        = _initial["screen_width"]
SCREEN_H        = _initial["screen_height"]

model_path = str((Path(__file__).parent / "hand_landmarker.task").resolve())

CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),
    (9,13),(13,14),(14,15),(15,16),
    (13,17),(0,17),(17,18),(18,19),(19,20),
]

CAM_W, CAM_H = 640, 480
Z_SCALE = 3.0
Y_SHIFT = 0.3

HIT_X_MIN = 0.2
HIT_X_MAX = 0.8
HIT_Y_MIN = 0.2
HIT_Y_MAX = 0.8

latest_frame       = None
calibMidFingerDist = 0.0
hit_point          = None
debug_str          = ""
laserMode          = False

calib_mode   = False
calib_corner = 0
calib_hits   = {}
CORNER_NAMES = ["TOP-LEFT", "TOP-RIGHT", "BOTTOM-LEFT", "BOTTOM-RIGHT"]

def lm_x(lm):
    return 1.0 - lm.x

def hit_to_screen(hit_x, hit_y):
    sx = (hit_x - HIT_X_MIN) / (HIT_X_MAX - HIT_X_MIN)
    sy = (hit_y - HIT_Y_MIN) / (HIT_Y_MAX - HIT_Y_MIN)
    sx = max(0.0, min(1.0, sx))
    sy = max(0.0, min(1.0, sy))
    return int(sx * SCREEN_WIDTH), int(sy * SCREEN_HEIGHT)

SMOOTH = 0.5
_smooth_hx = 0.5
_smooth_hy = 0.5

def finger_ray_screen_hit(base_lm, tip_lm, z_scale):
    dx = tip_lm.x - base_lm.x
    dy = (tip_lm.y + Y_SHIFT) - (base_lm.y + Y_SHIFT)
    dz = tip_lm.z - base_lm.z
    if dz > -0.01:
        return None
    t = -z_scale / dz
    t = min(t, 2.0)
    hit_x = base_lm.x + t * dx
    hit_y = (base_lm.y + Y_SHIFT) + t * dy
    return hit_x, hit_y

anchor               = None
holding_index_pinch  = False
holding_middle_pinch = False
last_pinch           = 0
index_pinch_time     = 0
middle_pinch_time    = 0
COOLDOWN             = 0.2
canvas               = None
prev_point           = None
pinch_buffer         = []
smooth_tip           = OneEuroPoint(alpha=0.25)
drawing_active       = False
locked_scale         = None
scale_thresh         = 0.15
scale_fail_count     = 0


def getScale(hand):
    dist  = distance(hand[0], hand[5])
    dist += distance(hand[5], hand[6])
    dist += distance(hand[6], hand[7])
    dist += distance(hand[7], hand[8])
    return dist

def distance(a, b):
    return math.sqrt((a.x - b.x)**2 + (a.y - b.y)**2)

def is_penPinch(hand, fingerThreshHold=0.15, thumbThreshHold=0.30):
    scale = getScale(hand)
    return (
        (distance(hand[12], hand[8])  / scale) < fingerThreshHold and
        (distance(hand[4],  hand[16]) / scale) < thumbThreshHold
    )

def is_Index_Pinch(hand, threshHold=0.15):
    return (distance(hand[4], hand[8]) / getScale(hand)) < threshHold

def is_Middle_Pinch(hand, threshHold=0.15):
    return (distance(hand[4], hand[12]) / getScale(hand)) < threshHold

def calibrate(hand):
    global anchor
    anchor = {"x": hand[0].x, "y": hand[0].y, "scale": getScale(hand)}

def get_cursor_pos(hand, anchor, screen_w, screen_h, sensitivity=1.6):
    if anchor is None:
        return
    half   = anchor["scale"] * sensitivity
    palm_x = hand[0].x
    palm_y = hand[0].y
    norm_x = (palm_x - (anchor["x"] - half)) / (2 * half)
    norm_y = (palm_y - (anchor["y"] - half)) / (2 * half)
    norm_x = max(0.0, min(1.0, norm_x))
    norm_y = max(0.0, min(1.0, norm_y))
    cursor_x = int(norm_x * screen_w)
    cursor_y = int(norm_y * screen_h)
    pyautogui.moveTo(cursor_x, cursor_y, _pause=False)

def draw_anchor_rect(frame, anchor):
    if anchor is None:
        return
    h, w = frame.shape[:2]
    half = anchor["scale"] * 1.6
    x1 = int((anchor["x"] - half) * w)
    y1 = int((anchor["y"] - half) * h)
    x2 = int((anchor["x"] + half) * w)
    y2 = int((anchor["y"] + half) * h)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 2)
    cx = int(anchor["x"] * w)
    cy = int(anchor["y"] * h)
    cv2.circle(frame, (cx, cy), 5, (255, 255, 255), -1)

def is_Fist(hand, fingerThreshHold=0.55, thumbThreshHold=0.2):
    scale = getScale(hand)
    return (
        (distance(hand[12], hand[0])  / scale) < fingerThreshHold and
        (distance(hand[4],  hand[14]) / scale) < thumbThreshHold
    )

def next_slide():
    global holding_index_pinch, last_pinch
    now = time.monotonic()
    if not holding_index_pinch and now - last_pinch > COOLDOWN:
        _send_key("right")
        print("next slide")
        last_pinch = now
    holding_index_pinch = True

def prev_slide():
    global holding_middle_pinch, last_pinch
    now = time.monotonic()
    if not holding_middle_pinch and now - last_pinch > COOLDOWN:
        _send_key("left")
        print("prev slide")
        last_pinch = now
    holding_middle_pinch = True

def _dispatch_gesture_action(gesture: dict):
    action = gesture.get("action", "")
    name   = gesture.get("name", "?")
    print(f"[gesture] Triggered: {name!r}  action={action}")
    if action == "next_slide":
        next_slide()
    elif action == "prev_slide":
        prev_slide()
    elif action == "left_click":
        pyautogui.click(_pause=False)
    elif action == "right_click":
        pyautogui.rightClick(_pause=False)
    elif action == "scroll_up":
        pyautogui.scroll(3)
    elif action == "scroll_down":
        pyautogui.scroll(-3)
    elif action == "custom_key":
        key = gesture.get("key", "")
        if key:
            _send_key(key)

def callback(result, mp_image, timestamp_ms):
    global latest_frame, calibMidFingerDist, hit_point, debug_str, laserMode
    global holding_index_pinch, holding_middle_pinch
    global index_pinch_time, middle_pinch_time
    global canvas, prev_point
    global _smooth_hx, _smooth_hy

    _cfg = load_config()
    laserMode = (_cfg["mouse_mode"] == "Point")

    frame = mp_image.numpy_view().copy()
    h, w, _ = frame.shape

    if laserMode:
        if result.hand_landmarks:
            hand = result.hand_landmarks[0]

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

            hit = finger_ray_screen_hit(hand[7], hand[8], Z_SCALE)
            if hit:
                _smooth_hx = SMOOTH * _smooth_hx + (1 - SMOOTH) * hit[0]
                _smooth_hy = SMOOTH * _smooth_hy + (1 - SMOOTH) * hit[1]
                hit = (_smooth_hx, _smooth_hy)

            hit_point = hit
            if hit:
                mx, my = hit_to_screen(hit[0], hit[1])
                pyautogui.moveTo(mx, my, _pause=False)

            base_lm   = hand[5]
            tip_lm    = hand[8]
            debug_str = f"base.z={base_lm.z:.4f}  tip.z={tip_lm.z:.4f}  dz={tip_lm.z - base_lm.z:.4f}"

            base  = hand[7]
            tip   = hand[8]
            ext   = 3.0
            ray_ex = int((base.x + ext * (tip.x - base.x)) * w)
            ray_ey = int((base.y + ext * (tip.y - base.y)) * h)
            cv2.line(frame, (int(base.x * w), int(base.y * h)), (ray_ex, ray_ey), (0, 180, 255), 1)

            if hit:
                hx = max(0, min(w-1, int(hit[0] * w)))
                hy = max(0, min(h-1, int(hit[1] * h)))
                cv2.drawMarker(frame, (hx, hy), (0, 255, 0), cv2.MARKER_CROSS, 20, 2)

            cv2.rectangle(frame, (0, 0), (w, 80), (0, 0, 0), -1)
            cv2.putText(frame,
                        f"calib={calibMidFingerDist:.4f}  curr={midFingerDist:.4f}  depth_ratio={depth_ratio:.2f}",
                        (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
            hit_str = (f"hit=({hit[0]:.3f},{hit[1]:.3f})  screen=({hit_to_screen(*hit)})"
                       if hit else "hit=None (finger parallel to screen)")
            cv2.putText(frame, f"Z_SCALE={Z_SCALE:.1f} (+/-)   {hit_str}",
                        (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)
            if calib_mode:
                corner_name = CORNER_NAMES[calib_corner] if calib_corner < 4 else "DONE"
                cv2.putText(frame, f"CALIB: point at {corner_name}, press C to record",
                            (8, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
        else:
            hit_point = None
        latest_frame = frame

    if canvas is None:
        canvas = frame.copy()
        canvas[:] = (0, 0, 0)

    if result.hand_landmarks and len(result.hand_landmarks) > 0:
        hand = result.hand_landmarks[0]

        raw_x = hand[8].x * w
        raw_y = hand[8].y * h
        x, y  = smooth_tip.update(raw_x, raw_y)
        current_point = (x, y)

        pinch = is_penPinch(hand)
        if pinch:
            if prev_point is not None:
                dx   = current_point[0] - prev_point[0]
                dy   = current_point[1] - prev_point[1]
                dist = int(math.hypot(dx, dy))
                for i in range(dist):
                    t  = i / dist if dist != 0 else 0
                    px = int(prev_point[0] + dx * t)
                    py = int(prev_point[1] + dy * t)
                    cv2.circle(canvas, (px, py), 2, (0, 0, 255), -1)
            prev_point = current_point
        else:
            prev_point = None

        do_slides = True
        if not laserMode:
            if is_Fist(hand):
                do_slides = False
                calibrate(hand)

        if is_Index_Pinch(hand) and do_slides:
            if index_pinch_time >= 2:
                next_slide()
            else:
                index_pinch_time += 1
        else:
            holding_index_pinch = False
            index_pinch_time    = 0

        if is_Middle_Pinch(hand) and do_slides:
            if middle_pinch_time >= 2:
                prev_slide()
            else:
                middle_pinch_time += 1
        else:
            holding_middle_pinch = False
            middle_pinch_time    = 0

        try:
            import gesture_engine as ge
            record_req = ge.poll_record_request()
            if record_req is not None:
                ge.complete_record(record_req, hand)
                print(f"[gestures] Recorded '{record_req['name']}'")
            for matched in ge.check_gestures(hand):
                _dispatch_gesture_action(matched)
        except ImportError:
            pass

        draw_anchor_rect(frame, anchor)
        get_cursor_pos(hand, anchor, SCREEN_W, SCREEN_H, SENSITIVITY)

        for a, b in CONNECTIONS:
            ax, ay = int(hand[a].x * w), int(hand[a].y * h)
            bx, by = int(hand[b].x * w), int(hand[b].y * h)
            cv2.line(frame, (ax, ay), (bx, by), (200, 200, 200), 1)

        for i, lm in enumerate(hand):
            cx, cy = int(lm.x * w), int(lm.y * h)
            cv2.circle(frame, (cx, cy), 4, (255, 255, 255), -1)
            cv2.putText(frame, str(i), (cx, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    else:
        prev_point = None

    latest_frame = cv2.addWeighted(frame, 0.7, canvas, 0.3, 0)

_cfg = load_config()
laserMode = (_cfg["mouse_mode"] == "Point")

options = HandLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path=model_path),
    running_mode=RunningMode.LIVE_STREAM,
    result_callback=callback,
    num_hands=_cfg["num_hands"],
)
landmarker = HandLandmarker.create_from_options(options)

cap = cv2.VideoCapture(_cfg["camera_index"])
ts_freq     = cv2.getTickFrequency()
frame_count = 0

if laserMode:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
    print("Hand skeleton + ray pointer running.")
    print("  +/- →  tune Z_SCALE   c → corner calib   r → reset   ESC → quit")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)
    mp_image  = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
    timestamp = int(cv2.getTickCount() / ts_freq * 1000)
    landmarker.detect_async(mp_image, timestamp)

    frame_count += 1
    if frame_count % 60 == 0:
        _live           = load_config()
        SENSITIVITY     = _live["sensitivity"]
        PINCH_THRESHOLD = _live["pinch_threshold"]
        SCREEN_W        = _live["screen_width"]
        SCREEN_H        = _live["screen_height"]

    display = latest_frame if latest_frame is not None else frame
    cv2.imshow("Hand Skeleton", display)

    if laserMode:
        key = cv2.waitKey(1) & 0xFF
        if key in (ord('+'), ord('=')):
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
                calib_mode, calib_corner, calib_hits = True, 0, {}
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
                    HIT_X_MIN, HIT_X_MAX = min(xs), max(xs)
                    HIT_Y_MIN, HIT_Y_MAX = min(ys), max(ys)
                    def hit_to_screen(hx, hy,
                                      xmin=HIT_X_MIN, xmax=HIT_X_MAX,
                                      ymin=HIT_Y_MIN, ymax=HIT_Y_MAX):
                        sx = max(0.0, min(1.0, (hx - xmin) / (xmax - xmin)))
                        sy = max(0.0, min(1.0, (hy - ymin) / (ymax - ymin)))
                        return int(sx * SCREEN_WIDTH), int(sy * SCREEN_HEIGHT)
                    calib_mode = False
                    print(f"Calibration done! X:[{HIT_X_MIN:.3f},{HIT_X_MAX:.3f}] Y:[{HIT_Y_MIN:.3f},{HIT_Y_MAX:.3f}]")

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()
landmarker.close()