import cv2
from pathlib import Path
from mediapipe.tasks import python
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

# ---------------------------------------------------------------------------
# Model path
# ---------------------------------------------------------------------------
model_path = str((Path(__file__).parent / "hand_landmarker.task").resolve())

# ---------------------------------------------------------------------------
# Drawing connections (same as before)
# ---------------------------------------------------------------------------
CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (5,9),(9,10),(10,11),(11,12),
    (9,13),(13,14),(14,15),(15,16),
    (13,17),(0,17),(17,18),(18,19),(19,20),
]

# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------
latest_frame = None

def callback(result, mp_image, timestamp_ms):
    global latest_frame

    frame = mp_image.numpy_view().copy()
    h, w, _ = frame.shape

    if result.hand_landmarks:
        hand = result.hand_landmarks[0]

        # --- Draw skeleton ---
        for a, b in CONNECTIONS:
            ax, ay = int(hand[a].x * w), int(hand[a].y * h)
            bx, by = int(hand[b].x * w), int(hand[b].y * h)
            cv2.line(frame, (ax, ay), (bx, by), (200, 200, 200), 1)

        # --- Draw points + coordinates ---
        for i, lm in enumerate(hand):
            cx, cy = int(lm.x * w), int(lm.y * h)

            cv2.circle(frame, (cx, cy), 4, (255, 255, 255), -1)
            cv2.putText(frame, str(i), (cx, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                        (255, 255, 255), 1)

            # Print coordinates
            print(f"Landmark {i}: ({cx}, {cy})")

    else:
        cv2.putText(frame, "NO HAND", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (100, 100, 100), 2)

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
ts_freq = cv2.getTickFrequency()

print("Press ESC to quit")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)

    mp_image = python.Image(image_format=python.ImageFormat.SRGB, data=frame)
    timestamp = int(cv2.getTickCount() / ts_freq * 1000)

    landmarker.detect_async(mp_image, timestamp)

    display = latest_frame if latest_frame is not None else frame
    cv2.imshow("Hand Skeleton (Tasks API)", display)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()
landmarker.close()