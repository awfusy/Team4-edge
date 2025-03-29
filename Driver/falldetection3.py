import cv2
import mediapipe as mp
import math
import time
import paho.mqtt.client as mqtt
from datetime import datetime
import json
import socketio
import base64
import threading
import sys
import queue
from concurrent.futures import ThreadPoolExecutor

# Globals
cap = None
camera_active = True
frame_skip = 2
prev_gray = None

# Thread pool for non-blocking MQTT/WebSocket sends
executor = ThreadPoolExecutor(max_workers=10)

# WebSocket client setup
sio = socketio.Client()

def connect_socket():
    if not sio.connected:
        try:
            sio.connect('http://192.168.18.49:5000')  # Replace with your Flask server IP
            print("WebSocket connected")
        except Exception as e:
            print(f"WebSocket connection failed: {e}")

connect_socket()

# MediaPipe Pose initialization
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5, min_tracking_confidence=0.5)
mp_drawing = mp.solutions.drawing_utils

# Pose Keypoints
KEYPOINTS = {
    "nose": mp_pose.PoseLandmark.NOSE,
    "neck": mp_pose.PoseLandmark.LEFT_SHOULDER,
    "left_hip": mp_pose.PoseLandmark.LEFT_HIP,
    "right_hip": mp_pose.PoseLandmark.RIGHT_HIP,
    "left_knee": mp_pose.PoseLandmark.LEFT_KNEE,
    "right_knee": mp_pose.PoseLandmark.RIGHT_KNEE,
}

# MQTT config
MQTT_BROKER = "192.168.18.138"
MQTT_PORT = 1883
MQTT_TOPIC = "video/emergency"

# Timeout-based shutdown
def exit_after_timeout():
    global cap
    time.sleep(300)
    print("\nTimeout reached (5 minutes). Shutting down gracefully...")
    if cap:
        cap.release()
    if sio.connected:
        sio.disconnect()
    if client.is_connected():
        client.disconnect()
    sys.exit(0)

timer_thread = threading.Thread(target=exit_after_timeout)
timer_thread.daemon = True
timer_thread.start()

# MQTT message handler
def on_message(client, userdata, message):
    global camera_active
    try:
        payload = json.loads(message.payload.decode('utf-8'))
        if message.topic == "video/monitor":
            camera_active = payload.get('activate', True)
            print(f"Camera {'activated' if camera_active else 'deactivated'} via MQTT")
    except Exception as e:
        print(f"Error processing MQTT message: {e}")

# MQTT client setup
client = mqtt.Client()
try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.subscribe("video/monitor")
    client.on_message = on_message
    client.loop_start()
except Exception as e:
    print(f"Failed to connect to MQTT broker: {e}")

# Helper functions
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

def detect_motion(gray):
    global prev_gray
    if prev_gray is None:
        prev_gray = gray
        return True

    delta = cv2.absdiff(prev_gray, gray)
    thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)[1]
    motion_detected = cv2.countNonZero(thresh) > 500
    prev_gray = gray
    return motion_detected

def detect_upper_body(frame):
    haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_upperbody.xml")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    bodies = haar.detectMultiScale(gray, 1.1, 5, minSize=(30, 30))
    return len(bodies) > 0

# Main loop
def generate_frames():
    global cap, camera_active
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    print("Camera ready")

    frame_count = 0

    while True:
        if not camera_active:
            if cap:
                cap.release()
                cap = None
            if sio.connected:
                sio.disconnect()
            time.sleep(1)
            continue

        if cap is None:
            cap = cv2.VideoCapture(0)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            connect_socket()
            print("Camera reactivated")

        ret, frame = cap.read()
        if not ret:
            print("Camera read failed")
            continue

        frame_count += 1
        if frame_count % frame_skip != 0:
            continue

        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if not detect_motion(gray):
            continue

        small_rgb = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (320, 240))
        results = pose.process(small_rgb)

        if results.pose_landmarks:
            mp_drawing.draw_landmarks(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
            state_mp = classify_patient_state(results.pose_landmarks.landmark, frame.shape)

            lhip = results.pose_landmarks.landmark[KEYPOINTS["left_hip"]]
            rhip = results.pose_landmarks.landmark[KEYPOINTS["right_hip"]]
            lhip_x, lhip_y = lhip.x * width, lhip.y * height
            rhip_x, rhip_y = rhip.x * width, rhip.y * height

            bed_x1, bed_y1 = width // 4, 0
            bed_x2, bed_y2 = 3 * width // 4, height
            cv2.rectangle(frame, (bed_x1, bed_y1), (bed_x2, bed_y2), (0, 0, 255), 2)

            if (bed_x1 < lhip_x < bed_x2 and bed_y1 < lhip_y < bed_y2) or \
               (bed_x1 < rhip_x < bed_x2 and bed_y1 < rhip_y < bed_y2):
                if state_mp == "Standing":
                    state_mp = "Laying Down"
            elif state_mp == "Laying Down":
                state_mp = "Fallen out of bed"

            state_ocv = "Standing" if detect_upper_body(frame) else "Sitting"

            label_color = (0, 255, 0) if state_mp == "Laying Down" or state_mp == state_ocv else (0, 0, 255)
            label = f"status:\nM: {state_mp}\nOCV: {state_ocv if state_mp != 'Laying Down' else 'N/A'}"

            y_offset = 50
            for line in label.split('\n'):
                cv2.putText(frame, line, (50, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, label_color, 1)
                y_offset += 20

            data = {
                "timestamp": datetime.now().isoformat(),
                "mediapipe_state": state_mp,
                "opencv_state": state_ocv,
                "source": "video"
            }

            # Publish via MQTT and send WebSocket in thread-safe way
            executor.submit(client.publish, MQTT_TOPIC, json.dumps(data), 2)

            _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            encoded_frame = base64.b64encode(jpeg).decode('utf-8')
            executor.submit(sio.emit, 'video_frame', encoded_frame)

        time.sleep(0.01)
        yield frame  # For MJPEG compatibility if needed

# Main runner
if __name__ == "__main__":
    for _ in generate_frames():
        pass
