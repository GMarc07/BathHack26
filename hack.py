import cv2
import mediapipe as mp
import threading
import time
import ctypes
import win32api
import win32con
from pathlib import Path
from mediapipe.tasks import python
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
model_path    = str((Path(__file__).parent / "hand_landmarker.task").resolve())
SCREEN_WIDTH  = ctypes.windll.user32.GetSystemMetrics(0)
SCREEN_HEIGHT = ctypes.windll.user32.GetSystemMetrics(1)

# --- Cursor ---
SMOOTH      = 0.4
ACTIVE_ZONE = (0.15, 0.85, 0.10, 0.90)  # (x_min, x_max, y_min, y_max) → full screen

# --- Pinch / click / drag ---
PINCH_THRESHOLD = 0.05   # normalised pinch distance (scaled by hand span)
PINCH_COOLDOWN  = 0.4    # seconds before another click can fire after releasing
DRAG_HOLD_TIME  = 0.25   # seconds to hold pinch before it becomes a drag
                         # lower  = drag triggers faster, harder to click
                         # higher = easier to click, slower to start drag

# --- Scroll ---
SCROLL_SPEED = 0.8

# --- Gesture debounce ---
GESTURE_COOLDOWN = 0.35

# ---------------------------------------------------------------------------
# Pre-built skeleton connections
# ---------------------------------------------------------------------------
CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),
    (9,13),(13,14),(14,15),(15,16),
    (13,17),(0,17),(17,18),(18,19),(19,20),
]
FINGER_PAIRS = [(8, 6), (12, 10), (16, 14), (20, 18)]  # tip, pip

# ---------------------------------------------------------------------------
# Win32 mouse helpers
# ---------------------------------------------------------------------------
def _move(x, y):    win32api.SetCursorPos((x, y))
def _left_down():   win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN,  0, 0)
def _left_up():     win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,    0, 0)
def _right_click():
    win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP,   0, 0)
def _scroll(delta): win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, int(delta))

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def palm_centre(hand):
    """Average of knuckle bases 5/9/13/17 — barely moves when fingers curl."""
    xs = [hand[i].x for i in (5, 9, 13, 17)]
    ys = [hand[i].y for i in (5, 9, 13, 17)]
    return sum(xs) / 4, sum(ys) / 4

def hand_span(hand):
    """Wrist→middle MCP — used to normalise pinch distance."""
    dx = hand[0].x - hand[9].x
    dy = hand[0].y - hand[9].y
    return (dx*dx + dy*dy) ** 0.5 or 0.001

def finger_extended(hand, tip, pip):
    return hand[tip].y < hand[pip].y

def classify_gesture(hand):
    """
    Returns: 'cursor' | 'pinch' | 'two_finger' | 'open_hand' | 'fist' | 'unknown'
    Pinch is checked first and overrides finger-extension logic.
    """
    span = hand_span(hand)
    dx   = hand[8].x - hand[4].x
    dy   = hand[8].y - hand[4].y
    pinch_dist = (dx*dx + dy*dy) ** 0.5 / span

    if pinch_dist < (PINCH_THRESHOLD / 0.15):
        return 'pinch'

    ext = [finger_extended(hand, t, p) for t, p in FINGER_PAIRS]
    idx, mid, rng, pnk = ext

    if     idx and not mid and not rng and not pnk: return 'cursor'
    if     idx and     mid and not rng and not pnk: return 'two_finger'
    if     idx and     mid and     rng and     pnk: return 'open_hand'
    if not idx and not mid and not rng and not pnk: return 'fist'
    return 'unknown'

def cam_to_screen(nx, ny):
    xmin, xmax, ymin, ymax = ACTIVE_ZONE
    sx = max(0.0, min(1.0, (nx - xmin) / (xmax - xmin)))
    sy = max(0.0, min(1.0, (ny - ymin) / (ymax - ymin)))
    return sx * SCREEN_WIDTH, sy * SCREEN_HEIGHT

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
_lock         = threading.Lock()
_latest_frame = None

_smooth_x     = SCREEN_WIDTH  / 2.0
_smooth_y     = SCREEN_HEIGHT / 2.0
_prev_raw_y   = None

_last_gesture = 'unknown'
_gesture_last = {}

# ---------------------------------------------------------------------------
# Pinch state machine
#
#   idle ──(pinch starts)──────────────► pending    button pressed, timer starts
#   pending ──(held >= DRAG_HOLD_TIME)──► dragging  confirmed drag, button stays down
#   pending ──(released early)──────────► idle      was a click: release button
#   dragging ──(pinch released)─────────► idle      drag end: release button
#
# Quick pinch  = click  (down + up within DRAG_HOLD_TIME)
# Held pinch   = drag   (down stays held, cursor steers, up on open hand)
# ---------------------------------------------------------------------------
_pinch_state      = 'idle'   # 'idle' | 'pending' | 'dragging'
_pinch_start_time = 0.0
_pinch_last_time  = 0.0      # cooldown guard

def _update_cursor(hand):
    global _smooth_x, _smooth_y
    raw_x, raw_y = cam_to_screen(*palm_centre(hand))
    _smooth_x = SMOOTH * _smooth_x + (1 - SMOOTH) * raw_x
    _smooth_y = SMOOTH * _smooth_y + (1 - SMOOTH) * raw_y
    _move(int(_smooth_x), int(_smooth_y))

def handle_pinch_active(hand):
    """Called every frame while gesture == 'pinch'."""
    global _pinch_state, _pinch_start_time

    _update_cursor(hand)
    now = time.monotonic()

    if _pinch_state == 'idle':
        if now - _pinch_last_time > PINCH_COOLDOWN:
            _left_down()                   # press button immediately
            _pinch_state      = 'pending'
            _pinch_start_time = now

    elif _pinch_state == 'pending':
        if now - _pinch_start_time >= DRAG_HOLD_TIME:
            _pinch_state = 'dragging'      # held long enough — now dragging

    # 'dragging': button held, cursor moves — nothing extra needed

def handle_pinch_released():
    """Called once when gesture leaves 'pinch'."""
    global _pinch_state, _pinch_last_time

    if _pinch_state == 'pending':
        # Released before drag threshold — complete the click
        _left_up()
        _pinch_last_time = time.monotonic()

    elif _pinch_state == 'dragging':
        # Drag ended — release button
        _left_up()
        _pinch_last_time = time.monotonic()

    # 'idle' means cooldown blocked the initial press — nothing to release
    _pinch_state = 'idle'

# ---------------------------------------------------------------------------
# Other gesture handlers
# ---------------------------------------------------------------------------
def handle_cursor(hand):
    _update_cursor(hand)

def handle_right_click():
    now = time.monotonic()
    if now - _gesture_last.get('two_finger', 0) > GESTURE_COOLDOWN:
        _gesture_last['two_finger'] = now
        _right_click()

def handle_scroll(hand):
    global _prev_raw_y
    _, raw_y = cam_to_screen(*palm_centre(hand))
    if _prev_raw_y is not None:
        delta = _prev_raw_y - raw_y
        if abs(delta) > 2:
            _scroll(int(delta * SCROLL_SPEED * 10))
    _prev_raw_y = raw_y

# ---------------------------------------------------------------------------
# MediaPipe callback
# ---------------------------------------------------------------------------
def callback(result, mp_image, timestamp_ms):
    global _latest_frame, _last_gesture, _prev_raw_y

    frame = mp_image.numpy_view().copy()
    h, w, _ = frame.shape

    if result.hand_landmarks:
        hand    = result.hand_landmarks[0]
        gesture = classify_gesture(hand)

        if _last_gesture == 'pinch' and gesture != 'pinch':
            handle_pinch_released()
        if gesture != 'open_hand':
            _prev_raw_y = None

        if   gesture == 'cursor':     handle_cursor(hand)
        elif gesture == 'pinch':      handle_pinch_active(hand)
        elif gesture == 'two_finger': handle_right_click()
        elif gesture == 'open_hand':  handle_scroll(hand)
        elif gesture == 'fist':       pass

        _last_gesture = gesture

        # --- Draw skeleton ---
        for a, b in CONNECTIONS:
            ax, ay = int(hand[a].x * w), int(hand[a].y * h)
            bx, by = int(hand[b].x * w), int(hand[b].y * h)
            cv2.line(frame, (ax, ay), (bx, by), (160, 160, 160), 1)

        for tip, _ in FINGER_PAIRS:
            cv2.circle(frame, (int(hand[tip].x * w), int(hand[tip].y * h)), 6, (200, 200, 200), -1)

        cv2.circle(frame, (int(hand[8].x * w), int(hand[8].y * h)), 10, (0,   0,   255), -1)
        cv2.circle(frame, (int(hand[4].x * w), int(hand[4].y * h)),  8, (0,   255,   0), -1)

        # Palm centre dot (yellow) — shows what's actually driving the cursor
        pcx, pcy = palm_centre(hand)
        cv2.circle(frame, (int(pcx * w), int(pcy * h)), 8, (0, 255, 255), -1)

        # --- Gesture label ---
        COLORS = {
            'cursor':     (255, 255, 255),
            'pinch':      (0,   255, 255),
            'two_finger': (255, 180,   0),
            'open_hand':  (180, 255,   0),
            'fist':       (100, 100, 255),
            'unknown':    (120, 120, 120),
        }
        if gesture == 'pinch':
            label = {'idle': 'PINCH (cooldown)', 'pending': 'CLICK?', 'dragging': 'DRAGGING'}.get(_pinch_state, 'PINCH')
        else:
            label = {'cursor': 'CURSOR', 'two_finger': 'RIGHT CLICK',
                     'open_hand': 'SCROLL', 'fist': 'FROZEN', 'unknown': '...'}.get(gesture, gesture.upper())

        cv2.rectangle(frame, (8, 8), (260, 38), (0, 0, 0), -1)
        cv2.putText(frame, label, (14, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.65, COLORS.get(gesture, (120,120,120)), 2, cv2.LINE_AA)

        # Active zone guide
        xmin, xmax, ymin, ymax = ACTIVE_ZONE
        cv2.rectangle(frame, (int(xmin*w), int(ymin*h)), (int(xmax*w), int(ymax*h)), (80, 80, 80), 1)

    else:
        if _pinch_state != 'idle':
            handle_pinch_released()
        cv2.putText(frame, 'NO HAND', (14, 29),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (60, 60, 60), 2, cv2.LINE_AA)

    with _lock:
        _latest_frame = frame

# ---------------------------------------------------------------------------
# MediaPipe setup
# ---------------------------------------------------------------------------
options = HandLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path=model_path),
    running_mode=RunningMode.LIVE_STREAM,
    result_callback=callback,
    num_hands=1,
)
hand_landmarker = HandLandmarker.create_from_options(options)

# ---------------------------------------------------------------------------
# Webcam loop
# ---------------------------------------------------------------------------
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)

ts_freq    = cv2.getTickFrequency()
fail_count = 0
MAX_FAILS  = 30

print("Hand mouse running.")
print("  Index finger only       → move cursor")
print("  Quick pinch             → left click")
print("  Hold pinch (0.25s+)     → drag (move hand, open to release)")
print("  Two fingers up          → right click")
print("  Open hand               → scroll")
print("  Fist                    → freeze cursor")
print("  ESC                     → quit")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        fail_count += 1
        if fail_count >= MAX_FAILS:
            print("Webcam lost. Exiting.")
            break
        continue
    fail_count = 0

    frame     = cv2.flip(frame, 1)
    mp_image  = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
    timestamp = int(cv2.getTickCount() / ts_freq * 1000)
    hand_landmarker.detect_async(mp_image, timestamp)

    with _lock:
        display = _latest_frame if _latest_frame is not None else frame

    cv2.imshow("Hand Mouse (ESC to quit)", display)
    if cv2.waitKey(1) & 0xFF == 27:
        break

# Cleanup — make sure mouse button isn't left down
if _pinch_state != 'idle':
    handle_pinch_released()
cap.release()
cv2.destroyAllWindows()
hand_landmarker.close()
