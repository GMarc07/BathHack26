import cv2
import mediapipe as mp
from pathlib import Path
from mediapipe.tasks import python
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
import math
import time
import keyboard


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
holding_index_pinch = False
holding_middle_pinch = False
last_pinch = 0
COOLDOWN = 0.2  # seconds


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

def is_Index_Pinch(hand, threshHold = 0.15):
    scale = getScale(hand)
    d1 = distance(hand[4],hand[8])
    d2 = distance(hand[4],hand[12])
    return (d1 / scale) < threshHold

def is_Middle_Pinch(hand, threshHold = 0.15):
    scale = getScale(hand)
    d1 = distance(hand[4],hand[12])
    d2 = distance(hand[4],hand[8])
    return (d1 / scale) < threshHold
    
# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------
def callback(result, mp_image, timestamp_ms):
    global latest_frame
    global holding_index_pinch
    global holding_middle_pinch
    global last_pinch

    frame = mp_image.numpy_view().copy()
    h, w, _ = frame.shape

    now = time.monotonic()

    if result.hand_landmarks:
        hand = result.hand_landmarks[0]

        # -------- INDEX PINCH --------
        if is_Index_Pinch(hand):
            if not holding_index_pinch:
                if now - last_pinch > COOLDOWN:
                    keyboard.send("right")
                    last_pinch = now

            holding_index_pinch = True
        else:
            holding_index_pinch = False

        # -------- MIDDLE PINCH --------
        if is_Middle_Pinch(hand):
            if not holding_middle_pinch:
                if now - last_pinch > COOLDOWN:
                    keyboard.send("left")
                    last_pinch = now

            holding_middle_pinch = True
        else:
            holding_middle_pinch = False

        # Draw skeleton
        for a, b in CONNECTIONS:
            ax, ay = int(hand[a].x * w), int(hand[a].y * h)
            bx, by = int(hand[b].x * w), int(hand[b].y * h)
            cv2.line(frame, (ax, ay), (bx, by), (200, 200, 200), 1)

        # Draw points + coordinates
        for i, lm in enumerate(hand):
            cx, cy = int(lm.x * w), int(lm.y * h)

            cv2.circle(frame, (cx, cy), 4, (255, 255, 255), -1)
            cv2.putText(frame, str(i), (cx, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                        (255, 255, 255), 1)

    latest_frame = frame

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