import cv2
import subprocess
import mediapipe as mp
import math
import time

# Start FFmpeg RTSP stream subprocess
FFMPEG_BIN = 'ffmpeg'
WIDTH = 640
HEIGHT = 480
FPS = 25

rtsp_url = "rtsp://localhost:8554/live"
ffmpeg_cmd = [
    FFMPEG_BIN,
    '-y',
    '-f', 'rawvideo',
    '-vcodec', 'rawvideo',
    '-pix_fmt', 'bgr24',
    '-s', f'{WIDTH}x{HEIGHT}',
    '-r', str(FPS),
    '-i', '-',  # Input from stdin
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p',
    '-preset', 'ultrafast',
    '-tune', 'zerolatency',
    '-f', 'rtsp',
    rtsp_url
]

ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

# Pose setup
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5, min_tracking_confidence=0.5)
mp_drawing = mp.solutions.drawing_utils

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

def calculate_angle(a, b, c):
    ba = (a[0] - b[0], a[1] - b[1])
    bc = (c[0] - b[0], c[1] - b[1])
    dot_product = ba[0] * bc[0] + ba[1] * bc[1]
    mag_ba = math.hypot(*ba)
    mag_bc = math.hypot(*bc)
    angle = math.acos(dot_product / (mag_ba * mag_bc))
    return math.degrees(angle)

def classify_patient_state(landmarks, frame_shape):
    def to_pixel_coords(lm):
        return int(lm.x * frame_shape[1]), int(lm.y * frame_shape[0])

    left_hip = to_pixel_coords(landmarks[mp_pose.PoseLandmark.LEFT_HIP])
    right_hip = to_pixel_coords(landmarks[mp_pose.PoseLandmark.RIGHT_HIP])
    neck = to_pixel_coords(landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER])
    left_knee = to_pixel_coords(landmarks[mp_pose.PoseLandmark.LEFT_KNEE])
    right_knee = to_pixel_coords(landmarks[mp_pose.PoseLandmark.RIGHT_KNEE])
    hips_mid = ((left_hip[0] + right_hip[0]) / 2, (left_hip[1] + right_hip[1]) / 2)
    knees_mid = ((left_knee[0] + right_knee[0]) / 2, (left_knee[1] + right_knee[1]) / 2)

    angle = calculate_angle(neck, hips_mid, knees_mid)
    if angle > 160:
        return "Laying Down"
    elif angle < 120:
        return "Sitting"
    else:
        return "Standing"

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame")
        break

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = pose.process(rgb_frame)

    if results.pose_landmarks:
        mp_drawing.draw_landmarks(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
        state = classify_patient_state(results.pose_landmarks.landmark, frame.shape)
        cv2.putText(frame, state, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        print("Pose State:", state)

    try:
        ffmpeg_process.stdin.write(frame.tobytes())
    except BrokenPipeError:
        print("FFmpeg pipe closed")
        break

cap.release()
ffmpeg_process.stdin.close()
ffmpeg_process.wait()
