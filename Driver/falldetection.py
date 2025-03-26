import cv2
import mediapipe as mp
import math
from flask import Flask, Response

# Initialize MediaPipe Pose
mp_pose = mp.solutions.pose

# Keypoints definition for MediaPipe
KEYPOINTS = {
    "nose": mp_pose.PoseLandmark.NOSE,
    "neck": mp_pose.PoseLandmark.LEFT_SHOULDER,
    "left_hip": mp_pose.PoseLandmark.LEFT_HIP,
    "right_hip": mp_pose.PoseLandmark.RIGHT_HIP,
    "left_knee": mp_pose.PoseLandmark.LEFT_KNEE,
    "right_knee": mp_pose.PoseLandmark.RIGHT_KNEE,
}

# Function to calculate angle between three points
def calculate_angle(a, b, c):
    ba = (a[0] - b[0], a[1] - b[1])
    bc = (c[0] - b[0], c[1] - b[1])
    dot_product = ba[0] * bc[0] + ba[1] * bc[1]
    mag_ba = math.hypot(*ba)
    mag_bc = math.hypot(*bc)
    angle = math.acos(dot_product / (mag_ba * mag_bc))
    return math.degrees(angle)

# Function to classify patient's state based on the pose
def classify_patient_state(landmarks, frame_shape):
    def to_pixel_coords(lm):
        return int(lm.x * frame_shape[1]), int(lm.y * frame_shape[0])

    nose = to_pixel_coords(landmarks[KEYPOINTS["nose"]])
    neck = to_pixel_coords(landmarks[KEYPOINTS["neck"]])
    left_hip = to_pixel_coords(landmarks[KEYPOINTS["left_hip"]])
    right_hip = to_pixel_coords(landmarks[KEYPOINTS["right_hip"]])
    left_knee = to_pixel_coords(landmarks[KEYPOINTS["left_knee"]])
    right_knee = to_pixel_coords(landmarks[KEYPOINTS["right_knee"]])

    hips_mid = ((left_hip[0] + right_hip[0]) / 2, (left_hip[1] + right_hip[1]) / 2)
    knees_mid = ((left_knee[0] + right_knee[0]) / 2, (left_knee[1] + right_knee[1]) / 2)

    angle = calculate_angle(neck, hips_mid, knees_mid)

    if angle > 160:
        return "Laying Down"
    elif angle < 120:
        return "Sitting"
    else:
        return "Standing"

# Function to generate frames for MJPEG streaming
def generate_frames():
    # Initialize MediaPipe Pose
    pose = mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5, min_tracking_confidence=0.5)
    mp_drawing = mp.solutions.drawing_utils

    # Initialize video capture from camera
    cap = cv2.VideoCapture(1)
    
    if not cap.isOpened():
        print("Error: Unable to access the camera")
        return

    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)  # Original resolution
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)  # Original resolution

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Failed to capture frame")
            break

        # Convert to RGB for MediaPipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Process with MediaPipe Pose
        pose_results = pose.process(rgb_frame)
        if pose_results.pose_landmarks:
            # Draw the pose landmarks on the frame
            mp_drawing.draw_landmarks(frame, pose_results.pose_landmarks, mp_pose.POSE_CONNECTIONS)

            # Get the patient state from MediaPipe
            state_mediapipe = classify_patient_state(pose_results.pose_landmarks.landmark, frame.shape)

            # Add text to frame
            cv2.putText(frame, f"State: {state_mediapipe}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)

        # Encode frame as JPEG
        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            print("Error: Failed to encode frame")
            continue
        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# Main program (Flask will call this to stream video)
app = Flask(__name__)

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
