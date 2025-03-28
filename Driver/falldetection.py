import cv2
import mediapipe as mp
import math
from flask import Flask, Response
import time
import paho.mqtt.client as mqtt
from datetime import datetime
import json

# Initialize MediaPipe Pose
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5, min_tracking_confidence=0.5)
mp_drawing = mp.solutions.drawing_utils

# Keypoints definition for MediaPipe
KEYPOINTS = {
    "nose": mp_pose.PoseLandmark.NOSE,
    "neck": mp_pose.PoseLandmark.LEFT_SHOULDER,
    "left_hip": mp_pose.PoseLandmark.LEFT_HIP,
    "right_hip": mp_pose.PoseLandmark.RIGHT_HIP,
    "left_knee": mp_pose.PoseLandmark.LEFT_KNEE,
    "right_knee": mp_pose.PoseLandmark.RIGHT_KNEE,
}

# MQTT Configuration
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "video/emergency"

# Add at the top of the file with other globals
camera_active = False

# MQTT subscriber setup
def on_message(client, userdata, message):
    """Handle incoming MQTT messages"""
    global camera_active
    try:
        payload = json.loads(message.payload.decode('utf-8'))
        if message.topic == "video/monitor":
            if payload['activate'] is True:
                camera_active = True
                print("Camera activation received")
            elif payload['activate'] is False:
                camera_active = False
                print("Camera deactivation received")
    except Exception as e:
        print(f"Error processing MQTT message: {e}")

# Initialize MQTT client
client = mqtt.Client()
try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
except Exception as e:
    print(f"Failed to connect to MQTT broker: {e}")

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

    # Extract keypoints
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

# Function to detect upper body using OpenCV
def detect_upper_body(frame):
    haar_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_upperbody.xml")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    bodies = haar_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    return len(bodies) > 0

# Function to generate frames for MJPEG streaming
def generate_frames():
    global camera_active
    cap = None

    while True:
        if camera_active:
            # Initialize camera if not already done
            if cap is None:
                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    print("Error: Unable to access the camera")
                    camera_active = False
                    continue
                cap.set(cv2.CAP_PROP_FPS, 30)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_HEIGHT, 480)
                print("Camera activated")
            
            try:
                ret, frame = cap.read()
                if not ret:
                    print("Error: Failed to capture frame")
                    continue

                # Process frame with MediaPipe and OpenCV
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Get frame dimensions for drawing the simulated bed
                height, width = frame.shape[:2]
                bed_x1, bed_y1 = width // 4, 0
                bed_x2, bed_y2 = 3 * width // 4, height
                bed_box = (bed_x1, bed_y1, bed_x2, bed_y2)

                # Draw simulated bed (as a red rectangle)
                cv2.rectangle(frame, (bed_x1, bed_y1), (bed_x2, bed_y2), (0, 0, 255), 2)
                cv2.putText(frame, "Bed", (bed_x1, bed_y1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

                # Process with MediaPipe Pose
                pose_results = pose.process(rgb_frame)
                if pose_results.pose_landmarks:
                    # Draw the pose landmarks on the frame
                    mp_drawing.draw_landmarks(frame, pose_results.pose_landmarks, mp_pose.POSE_CONNECTIONS)

                    # Get the patient state from MediaPipe
                    state_mediapipe = classify_patient_state(pose_results.pose_landmarks.landmark, frame.shape)

                    # Check if the patient is inside the simulated bed based on hips
                    left_hip_x = pose_results.pose_landmarks.landmark[mp_pose.PoseLandmark.LEFT_HIP].x * width
                    left_hip_y = pose_results.pose_landmarks.landmark[mp_pose.PoseLandmark.LEFT_HIP].y * height
                    right_hip_x = pose_results.pose_landmarks.landmark[mp_pose.PoseLandmark.RIGHT_HIP].x * width
                    right_hip_y = pose_results.pose_landmarks.landmark[mp_pose.PoseLandmark.RIGHT_HIP].y * height

                    # If the hips are inside the simulated bed, prevent standing detection
                    if (bed_x1 < left_hip_x < bed_x2 and bed_y1 < left_hip_y < bed_y2) or (bed_x1 < right_hip_x < bed_x2 and bed_y1 < right_hip_y < bed_y2):
                        if state_mediapipe == "Standing":
                            state_mediapipe = "Laying Down"  # Change standing to laying down if inside bed

                    # If the person is "Laying Down" and outside the bed, change state to "Fallen out of bed"
                    if state_mediapipe == "Laying Down":
                        if not (bed_x1 < left_hip_x < bed_x2 and bed_y1 < left_hip_y < bed_y2) and not (bed_x1 < right_hip_x < bed_x2 and bed_y1 < right_hip_y < bed_y2):
                            state_mediapipe = "Fallen out of bed"

                    # Use OpenCV to detect the upper body
                    state_opencv = "Standing" if detect_upper_body(frame) else "Sitting"  # Basic assumption

                    # Combine both detections
                    if state_mediapipe == "Laying Down":
                        label = f"status:\nM: {state_mediapipe}\nOCV: N/A"
                        color = (0, 255, 0)  # Red for laying down (MediaPipe takes priority)
                    elif state_mediapipe == state_opencv:
                        label = f"status:\nM: {state_mediapipe}\nOCV: {state_opencv}"
                        color = (0, 255, 0)  # Green for both states matching
                    else:
                        label = f"status:\nM: {state_mediapipe}\nOCV: {state_opencv}"
                        color = (0, 0, 255)  # Red for mismatch

                    # Split the label into lines and add them one by one
                    y_offset = 50
                    for line in label.split('\n'):
                        cv2.putText(frame, line, (50, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                        y_offset += 20  # Move to the next line
                    
                    # Take these for MQTT, send it to the nurse dashboard via MQTT
                    mqttDataMP = state_mediapipe
                    mqttDataOCV = state_opencv        
                    print(mqttDataMP)
                    print(mqttDataOCV) 

                    # Add MQTT publishing here
                    mqtt_data = {
                        "timestamp": datetime.now().isoformat(),
                        "mediapipe_state": mqttDataMP,
                        "opencv_state": mqttDataOCV,
                        "source": "video"
                    }
                    
                    try:
                        client.publish(MQTT_TOPIC, json.dumps(mqtt_data), qos=2)
                        print(f"States sent via MQTT: MP={mqttDataMP}, OCV={mqttDataOCV}")
                    except Exception as e:
                        print(f"Failed to send MQTT message: {e}")
                
                # Encode and yield frame
                ret, buffer = cv2.imencode('.jpg', frame)
                if not ret:
                    print("Error: Failed to encode frame")
                    continue
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

            except Exception as e:
                print(f"Error processing frame: {e}")
                continue

        else:
            # Deactivate and release camera if it was active
            if cap is not None:
                cap.release()
                cap = None
                print("Camera deactivated")
            time.sleep(1)  # Wait before checking again
            continue

# Flask app to serve video stream
app = Flask(__name__)

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
