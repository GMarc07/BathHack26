import cv2
import mediapipe as mp
from pathlib import Path
from mediapipe.tasks import python
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

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
calibMidFingerDist = 0.0

# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------
def callback(result, mp_image, timestamp_ms):
    global latest_frame, calibMidFingerDist

    frame = mp_image.numpy_view().copy()
    h, w, _ = frame.shape

    if result.hand_landmarks:
        hand = result.hand_landmarks[0]
        midFingerNodes = [12,11,10,9,0,0]
        if calibMidFingerDist == 0:
            
            for i in midFingerNodes:
                difx = hand[i].x-hand[i+1].x
                dify = hand[i].y-hand[i+1].y
                calibMidFingerDist +=  difx*difx + dify*dify
        midFingerDist = 0.0
        for i in midFingerNodes:
                difx = hand[i].x-hand[i+1].x
                dify = hand[i].y-hand[i+1].y
                midFingerDist +=  difx*difx + dify*dify

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
            cv2.putText(frame, str(calibMidFingerDist) + " " + str(midFingerDist), (400, 200),
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