import cv2
import mediapipe as mp
from pathlib import Path
from mediapipe.tasks import python
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
import math
import win32api
import json
#import win32api

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_cfg_path = Path(__file__).parent / "tracker_config.json"

def load_config():
    cfg = json.loads(_cfg_path.read_text()) if _cfg_path.exists() else {}
    return {
        "sensitivity":      cfg.get("sensitivity", 1.6),
        "pinch_threshold":  cfg.get("pinch_threshold", 0.15),
        "screen_width":     cfg.get("screen_width", 1920),
        "screen_height":    cfg.get("screen_height", 1080),
        "num_hands":        cfg.get("num_hands", 1),
        "camera_index":     cfg.get("camera_index", 1),
    }

_initial = load_config()
SENSITIVITY     = _initial["sensitivity"]
PINCH_THRESHOLD = _initial["pinch_threshold"]
SCREEN_W        = _initial["screen_width"]
SCREEN_H        = _initial["screen_height"]

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

latest_frame = None

anchor = None

def getScale(hand):
    dist = 0
    dist += distance(hand[0],hand[5])
    dist += distance(hand[5],hand[6])
    dist += distance(hand[6],hand[7])
    dist += distance(hand[7],hand[8])
    return dist

def distance(a, b):
    return math.sqrt((a.x - b.x)**2 + (a.y - b.y)**2)

def calibrate(hand):
    global anchor
    anchor = {
        "x": hand[0].x,
        "y": hand[0].y,
        "scale": getScale(hand)
    }
    print("Calibrated "+ str(anchor["x"]) + " " + str(anchor["y"]))


def get_cursor_pos(hand, anchor, screen_w, screen_h, sensitivity=1.6):
    if anchor is None:
        return None

    half = anchor["scale"] * sensitivity

    palm_x = hand[0].x
    palm_y = hand[0].y

    norm_x = (palm_x - (anchor["x"] - half)) / (2 * half)
    norm_y = (palm_y - (anchor["y"] - half)) / (2 * half)

    norm_x = max(0.0, min(1.0, norm_x))
    norm_y = max(0.0, min(1.0, norm_y))

    cursor_x = int(norm_x * screen_w)
    cursor_y = int(norm_y * screen_h)

    #win32api.SetCursorPos((cursor_x, cursor_y))

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


def is_Pinch(hand, threshHold=None):
    if threshHold is None:
        threshHold = PINCH_THRESHOLD
    scale = getScale(hand)
    d = distance(hand[4],hand[8])
    return (d / scale) < threshHold
    
# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------
def callback(result, mp_image, timestamp_ms):
    global latest_frame

    frame = mp_image.numpy_view().copy()
    h, w, _ = frame.shape

    if result.hand_landmarks:
        hand = result.hand_landmarks[0]
        if is_Pinch(hand):
            calibrate(hand)
        
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
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                        (255, 255, 255), 1)

    latest_frame = frame

# ---------------------------------------------------------------------------
# MediaPipe setup
# ---------------------------------------------------------------------------
_cfg = load_config()

options = HandLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path=model_path),
    running_mode=RunningMode.LIVE_STREAM,
    result_callback=callback,
    num_hands=_cfg["num_hands"],
)

landmarker = HandLandmarker.create_from_options(options)

# ---------------------------------------------------------------------------
# Webcam loop
# ---------------------------------------------------------------------------
cap = cv2.VideoCapture(_cfg["camera_index"])
ts_freq = cv2.getTickFrequency()
frame_count = 0

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)

    mp_image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=frame
    )

    timestamp = int(cv2.getTickCount() / ts_freq * 1000)
    landmarker.detect_async(mp_image, timestamp)

    # Reload hot-reloadable config values every 60 frames
    frame_count += 1
    if frame_count % 60 == 0:
        _live = load_config()
        SENSITIVITY     = _live["sensitivity"]
        PINCH_THRESHOLD = _live["pinch_threshold"]
        SCREEN_W        = _live["screen_width"]
        SCREEN_H        = _live["screen_height"]

    display = latest_frame if latest_frame is not None else frame
    cv2.imshow("Hand Skeleton", display)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()
landmarker.close()