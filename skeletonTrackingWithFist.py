import cv2
import mediapipe as mp
from pathlib import Path
from mediapipe.tasks import python
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
import math

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
    
# globals 
canvas = None
prev_point = None
pinch_buffer = []
smooth_tip = OneEuroPoint(alpha=0.25)

drawing_active = False
locked_scale = None
prev_point = None

scale_thresh = 0.15
scale_fail_count = 0
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


def getScale(hand):
    #0-5, 5-6, 6-7, 7-8
    dist = 0
    dist += distance(hand[0],hand[5])
    dist += distance(hand[5],hand[6])
    dist += distance(hand[6],hand[7])
    dist += distance(hand[7],hand[8])
    return dist

def distance(a, b):
    return math.sqrt((a.x - b.x)**2 + (a.y - b.y)**2)

def is_penPinch(hand, fingerThreshHold = 0.15, thumbThreshHold = 0.30):
    scale = getScale(hand)
    indexDistance = distance(hand[12],hand[8])
    thumbDistance = distance(hand[4], hand[16])
    return ((indexDistance / scale) < fingerThreshHold) and ((thumbDistance / scale) < thumbThreshHold)
    
# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------
def callback(result, mp_image, timestamp_ms):
    global latest_frame, canvas, prev_point

    frame = mp_image.numpy_view().copy()
    h, w, _ = frame.shape

    if canvas is None:
        canvas = frame.copy()
        canvas[:] = (0, 0, 0)

    if result.hand_landmarks and len(result.hand_landmarks) > 0:
        hand = result.hand_landmarks[0]

        # smoothed pen tip
        raw_x = hand[8].x * w
        raw_y = hand[8].y * h
        x, y = smooth_tip.update(raw_x, raw_y)
        current_point = (x, y)

        # -------------------------
        # PINCH = DRAW
        # -------------------------
        pinch = is_penPinch(hand)

        if pinch:
            if prev_point is not None:
                cv2.line(canvas, prev_point, current_point, (0, 0, 255), 4)

            prev_point = current_point

        else:
            # pen lifted
            prev_point = None

        # skeleton overlay
        for a, b in CONNECTIONS:
            ax, ay = int(hand[a].x * w), int(hand[a].y * h)
            bx, by = int(hand[b].x * w), int(hand[b].y * h)
            cv2.line(frame, (ax, ay), (bx, by), (200, 200, 200), 1)

    else:
        prev_point = None  # lost tracking → stop drawing

    latest_frame = cv2.addWeighted(frame, 0.7, canvas, 0.3, 0)

# ---------------------------------------------------------------------------
# MediaPipe setup (NEW API)
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

    display = latest_frame if latest_frame is not None else frame
    cv2.imshow("Hand Skeleton", display)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()
landmarker.close()