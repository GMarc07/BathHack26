import cv2
import mediapipe as mp
import threading
import time
import pyautogui
from AppKit import NSScreen
from pathlib import Path
from mediapipe.tasks import python
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

# Remove pyautogui import, replace with:
from Quartz.CoreGraphics import (
    CGEventCreateMouseEvent, CGEventPost,
    kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp,
    kCGMouseButtonLeft, kCGHIDEventTap, CGPointMake
)

# --- Config ---
model_path    = str((Path(__file__).parent / "hand_landmarker.task").resolve())
screen        = NSScreen.mainScreen().frame()
SCREEN_WIDTH  = int(screen.size.width)
SCREEN_HEIGHT = int(screen.size.height)
PINCH_THRESHOLD = 0.05
PINCH_COOLDOWN  = 0.4
SMOOTH          = 0.4

pyautogui.FAILSAFE = False  # prevent pyautogui from raising on screen edge

CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),
    (9,13),(13,14),(14,15),(15,16),
    (13,17),(0,17),(17,18),(18,19),(19,20),
]

def _move(x, y):
    event = CGEventCreateMouseEvent(None, kCGEventMouseMoved, CGPointMake(x, y), kCGMouseButtonLeft)
    CGEventPost(kCGHIDEventTap, event)

def _click():
    pos = CGPointMake(_smooth_x, _smooth_y)
    down = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, pos, kCGMouseButtonLeft)
    up   = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp,   pos, kCGMouseButtonLeft)
    CGEventPost(kCGHIDEventTap, down)
    CGEventPost(kCGHIDEventTap, up)
# --- Shared state ---
_lock            = threading.Lock()
_latest_frame    = None
_pinch_last_time = 0.0
_smooth_x        = 0.0
_smooth_y        = 0.0


def callback(result, mp_image, timestamp_ms):
    global _latest_frame, _pinch_last_time, _smooth_x, _smooth_y

    frame = mp_image.numpy_view().copy()
    h, w, _ = frame.shape

    if result.hand_landmarks:
        hand      = result.hand_landmarks[0]
        index_tip = hand[8]
        thumb_tip = hand[4]

        raw_x = index_tip.x * SCREEN_WIDTH
        raw_y = index_tip.y * SCREEN_HEIGHT
        _smooth_x = SMOOTH * _smooth_x + (1 - SMOOTH) * raw_x
        _smooth_y = SMOOTH * _smooth_y + (1 - SMOOTH) * raw_y
        _move(int(_smooth_x), int(_smooth_y))

        dx   = index_tip.x - thumb_tip.x
        dy   = index_tip.y - thumb_tip.y
        dist = (dx*dx + dy*dy) ** 0.5

        now = time.monotonic()
        pinching = dist < PINCH_THRESHOLD
        if pinching and (now - _pinch_last_time) > PINCH_COOLDOWN:
            _pinch_last_time = now
            _click()

        for a, b in CONNECTIONS:
            ax, ay = int(hand[a].x * w), int(hand[a].y * h)
            bx, by = int(hand[b].x * w), int(hand[b].y * h)
            cv2.line(frame, (ax, ay), (bx, by), (180, 180, 180), 1)

        ix_px = int(index_tip.x * w)
        iy_px = int(index_tip.y * h)
        tx_px = int(thumb_tip.x * w)
        ty_px = int(thumb_tip.y * h)
        cv2.circle(frame, (ix_px, iy_px), 10, (0, 0, 255), -1)
        cv2.circle(frame, (tx_px, ty_px),  8, (0, 255, 0), -1)

        if pinching:
            mx = (ix_px + tx_px) // 2
            my = (iy_px + ty_px) // 2
            cv2.circle(frame, (mx, my), 18, (0, 255, 255), 3)

    with _lock:
        _latest_frame = frame


options = HandLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path=model_path),
    running_mode=RunningMode.LIVE_STREAM,
    result_callback=callback,
    num_hands=1,
)
hand_landmarker = HandLandmarker.create_from_options(options)

# CAP_DSHOW removed — not available on macOS
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)

ts_freq = cv2.getTickFrequency()

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame    = cv2.flip(frame, 1)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
    timestamp = int(cv2.getTickCount() / ts_freq * 1000)
    hand_landmarker.detect_async(mp_image, timestamp)

    with _lock:
        display = _latest_frame if _latest_frame is not None else frame

    cv2.imshow("Hand Tracking (ESC to quit)", display)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()
hand_landmarker.close()