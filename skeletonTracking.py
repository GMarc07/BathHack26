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
anchor = None
holding_index_pinch = False
holding_middle_pinch = False
last_pinch = 0
index_pinch_time = 0
middle_pinch_time = 0
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
    d = distance(hand[4],hand[8])
    return (d / scale) < threshHold

def is_Middle_Pinch(hand, threshHold = 0.15):
    scale = getScale(hand)
    d = distance(hand[4],hand[12])
    return (d / scale) < threshHold

def calibrate(hand):
    global anchor
    anchor = {
        "x": hand[0].x,       # wrist position as centre of reference
        "y": hand[0].y,
        "scale": getScale(hand)
    }
    # print("Calibrated "+ str(anchor["x"]) + " " + str(anchor["y"]))

def draw_anchor_rect(frame, anchor):
    if anchor is None:
        return

    h, w = frame.shape[:2]
    
    half = anchor["scale"] * 1.6  # how far in normalised coords to reach screen edge
    
    # convert normalised coords to pixels
    x1 = int((anchor["x"] - half) * w)
    y1 = int((anchor["y"] - half) * h)
    x2 = int((anchor["x"] + half) * w)
    y2 = int((anchor["y"] + half) * h)
    
    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 2)
    
    # optional: draw the anchor centre point too
    cx = int(anchor["x"] * w)
    cy = int(anchor["y"] * h)
    cv2.circle(frame, (cx, cy), 5, (255, 255, 255), -1)

# checks for closed fist facing camera
# fingers closed with open thumb will return false
def is_Fist(hand, fingerThreshHold = 0.55, thumbThreshHold = 0.2):
    scale = getScale(hand)
    fingersDistance = distance(hand[12],hand[0]) # distance between tip of middle finger and centre of hand
    thumbDistance = distance(hand[4], hand[14] ) # distance between thumb and second knuckle of fourth finger
    return ((fingersDistance / scale) < fingerThreshHold) and ((thumbDistance / scale) < thumbThreshHold)
    
def next_slide():
    global holding_index_pinch
    global last_pinch
    now = time.monotonic()
    if not holding_index_pinch:
        if now - last_pinch > COOLDOWN:
            keyboard.send("right")
            print("next slide")
            last_pinch = now
    holding_index_pinch = True

def prev_slide():
    global holding_middle_pinch
    global last_pinch
    now = time.monotonic()
    if not holding_middle_pinch:
        if now - last_pinch > COOLDOWN:
            keyboard.send("left")
            print("prev slide")
            last_pinch = now
    holding_middle_pinch = True

# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------
def callback(result, mp_image, timestamp_ms):
    global latest_frame
    global holding_index_pinch
    global holding_middle_pinch
    global index_pinch_time
    global middle_pinch_time

    frame = mp_image.numpy_view().copy()
    h, w, _ = frame.shape

    if result.hand_landmarks:
        hand = result.hand_landmarks[0]

        if is_Fist(hand):
            do_slides = False
            calibrate(hand)
        else:
            do_slides = True

        # -------- INDEX PINCH --------#
        if is_Index_Pinch(hand) and do_slides:
            if index_pinch_time >= 5:
                next_slide()
            else:
                index_pinch_time += 1
        else:
            holding_index_pinch = False
            index_pinch_time = 0


        # -------- MIDDLE PINCH --------
        if is_Middle_Pinch(hand) and do_slides:
            if middle_pinch_time >= 5:
                prev_slide()
            else:
                middle_pinch_time += 1
        else:
            holding_middle_pinch = False
            middle_pinch_time = 0
        
        draw_anchor_rect(frame,anchor)

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