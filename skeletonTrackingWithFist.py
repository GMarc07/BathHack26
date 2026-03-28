import cv2
import mediapipe as mp
import math
import pyautogui
import time
import pygetwindow as gw
from pathlib import Path
from mediapipe.tasks import python
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

# -----------------------------
# POWERPOINT CONTROL
# -----------------------------
def activate_powerpoint():
    windows = gw.getWindowsWithTitle("PowerPoint")
    if windows:
        windows[0].activate()

    time.sleep(1)

    pyautogui.press("f5")      # slideshow
    time.sleep(1)

    pyautogui.hotkey("ctrl", "p")  # pen tool
    time.sleep(0.5)


# -----------------------------
# ONE EURO FILTER (better tuned)
# -----------------------------
class OneEuroPoint:
    def __init__(self, min_cutoff=2.0, beta=0.02):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.x = None
        self.y = None
        self.prev_time = None
        self.dx = 0
        self.dy = 0

    def update(self, x, y):
        if self.x is None:
            self.x, self.y = x, y
            return x, y

        # velocity
        self.dx = x - self.x
        self.dy = y - self.y

        cutoff = self.min_cutoff + self.beta * (abs(self.dx) + abs(self.dy))

        a = 1.0 / (1.0 + cutoff)

        self.x = a * x + (1 - a) * self.x
        self.y = a * y + (1 - a) * self.y

        return int(self.x), int(self.y)


# -----------------------------
# GLOBAL STATE
# -----------------------------
smooth_tip = OneEuroPoint()
pinch_buffer = []

mouse_down = False
prev_point = None

screen_w, screen_h = pyautogui.size()

frame_counter = 0
FRAME_SKIP = 2

DEADZONE = 5

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0


# -----------------------------
# MODEL
# -----------------------------
model_path = str((Path(__file__).parent / "hand_landmarker.task").resolve())


# -----------------------------
# HELPERS
# -----------------------------
def distance(a, b):
    return math.sqrt((a.x - b.x)**2 + (a.y - b.y)**2)


def getScale(hand):
    return (
        distance(hand[0], hand[5]) +
        distance(hand[5], hand[6]) +
        distance(hand[6], hand[7]) +
        distance(hand[7], hand[8])
    )


def is_pinch(hand):
    scale = getScale(hand)

    index_dist = distance(hand[8], hand[12])
    thumb_dist = distance(hand[4], hand[16])

    return (index_dist / scale < 0.15) and (thumb_dist / scale < 0.3)


# -----------------------------
# CALLBACK
# -----------------------------
def callback(result, mp_image, timestamp_ms):
    global mouse_down, prev_point, frame_counter

    frame_counter += 1
    if frame_counter % FRAME_SKIP != 0:
        return

    frame = mp_image.numpy_view().copy()
    h, w, _ = frame.shape

    if not result.hand_landmarks:
        return

    hand = result.hand_landmarks[0]

    # -------------------------
    # PINCH STABILITY BUFFER
    # -------------------------
    pinch_buffer.append(is_pinch(hand))
    if len(pinch_buffer) > 9:
        pinch_buffer.pop(0)

    pinch = sum(pinch_buffer) >= 7

    # -------------------------
    # LANDMARK → SCREEN SPACE
    # -------------------------
    raw_x = hand[8].x * w
    raw_y = hand[8].y * h

    screen_x = int((raw_x / w) * screen_w)
    screen_y = int((raw_y / h) * screen_h)

    # -------------------------
    # SMOOTH IN SCREEN SPACE
    # -------------------------
    screen_x, screen_y = smooth_tip.update(screen_x, screen_y)

    # -------------------------
    # DEADZONE (kills jitter)
    # -------------------------
    if prev_point is not None:
        if abs(screen_x - prev_point[0]) < DEADZONE and abs(screen_y - prev_point[1]) < DEADZONE:
            screen_x, screen_y = prev_point

    # -------------------------
    # DRAW CONTROL (FIXED)
    # -------------------------
    if pinch:
        # ALWAYS move cursor while pinching
        pyautogui.moveTo(screen_x, screen_y)

        # ONLY press once (start stroke)
        if not mouse_down:
            pyautogui.mouseDown(button="left")
            mouse_down = True
            
        pyautogui.dragTo(screen_x, screen_y, duration=0)
    else:
        # ONLY release once (end stroke)
        if mouse_down:
            pyautogui.mouseUp(button="left")
            mouse_down = False

    prev_point = (screen_x, screen_y)


# -----------------------------
# MEDIA PIPE SETUP
# -----------------------------
options = HandLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path=model_path),
    running_mode=RunningMode.LIVE_STREAM,
    result_callback=callback,
    num_hands=1,
)

landmarker = HandLandmarker.create_from_options(options)

activate_powerpoint()


# -----------------------------
# CAMERA LOOP
# -----------------------------
cap = cv2.VideoCapture(0)
ts_freq = cv2.getTickFrequency()

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

    cv2.imshow("Hand Tracking", frame)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()
landmarker.close()