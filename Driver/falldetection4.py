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
from concurrent.futures import ThreadPoolExecutor

# WebSocket client setup
sio = socketio.Client()
try:
	sio.connect('http://192.168.18.49:5000')  # Replace with your Flask server IP
	print("WebSocket connected")
except Exception as e:
	print(f"WebSocket connection failed: {e}")

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
MQTT_BROKER = "192.168.61.254"
MQTT_PORT = 1883
MQTT_TOPIC = "video/emergency"

# Camera control flag
camera_active = False
video_timer = None
video_timer_lock = threading.Lock()
camera_state_lock = threading.Lock()

# Thread pool for non-blocking tasks
executor = ThreadPoolExecutor(max_workers=5)

# Function to stop video feed after timeout
def stop_video_after_timeout():
    global camera_active
    with video_timer_lock:
        camera_active = False
        print("Camera deactivated after 10 seconds timeout")
        camerastate_data = {
            "timestamp": datetime.now().isoformat(),
            "source": "video",
            "cameraState": camera_active
        }
        executor.submit(client.publish, MQTT_TOPIC, json.dumps(camerastate_data), 2)

# MQTT subscriber setup
def on_message(client, userdata, message):
    global camera_active, video_timer
    try:
        payload = json.loads(message.payload.decode('utf-8'))
        if message.topic == "video/monitor":
            with camera_state_lock:
                source = payload.get('source', '')
                activate = payload.get('activate', False)

                # ✅ Ignore activation if already active
                if activate and camera_active:
                    #print("Camera activation ignored — already active")
                    return
                
                # ✅ Ignore deactivation if already inactive
                if not activate and not camera_active:
                    #print("Camera deactivation ignored — already inactive")
                    return
                
                # ✅ Otherwise, update state
                camera_active = activate
                #print(f"Camera {'activated' if camera_active else 'deactivated'} via MQTT")
                if activate:                    
                    try:
                        sio.connect('http://192.168.61.139:5000')
                        #print("WebSocket connnected")
                    except Exception as e:
                        print(f"WebSocket connection failed: {e}")     

					# If the source is "audio", set the timer
                    if source == "audio":						
                        if video_timer and video_timer.is_alive():
                            video_timer.cancel()  # Cancel any existing timer
                        video_timer = threading.Timer(20, stop_video_after_timeout)
                        video_timer.start()
                        print("Camera will deactivate after timeout (20s) due to audio trigger.")

                    # If the source is "proximity", no timeout is set
                    elif source == "proximity":

                        if video_timer and video_timer.is_alive():
                            video_timer.cancel()  # Cancel any existing timer
                        print("Camera activated via proximity sensor, no timeout set.")

                    # Publish the camera activation state after it has been updated                    
                    #print("camera_activate State", camera_active)
                    camerastate_data = {
                        'timestamp': datetime.now().isoformat(),
                        'source': source,
                        'cameraState': camera_active
                    }
                    executor.submit(client.publish, MQTT_TOPIC, json.dumps(camerastate_data), 2)
                else:
                    # Publish deactivation message if camera is deactivated
                    camerastate_data = {
                        'timestamp': datetime.now().isoformat(),
                        'source': source,
                        'cameraState': camera_active
                    }
                    executor.submit(client.publish, MQTT_TOPIC, json.dumps(camerastate_data), 2)
    except Exception as e:
        print(f"Error processing MQTT message: {e}")


# Initialize MQTT client
client = mqtt.Client()
client.on_message = on_message
try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.subscribe("video/monitor")
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

# Classify patient state using pose landmarks
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

# Detect upper body using Haar Cascade
def detect_upper_body(frame):
    haar_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_upperbody.xml")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    bodies = haar_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    return len(bodies) > 0

# Frame processing loop
def generate_frames():
    global camera_active
    cap = None

    while True:
        with camera_state_lock:
            current_state = camera_active

        if current_state:
            if cap is None:
                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    print("Error: Unable to access the camera")
                    camera_active = False
                    continue
                cap.set(cv2.CAP_PROP_FPS, 30)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                #print("Camera activated")

            try:
                ret, frame = cap.read()
                if not ret:
                    print("Error: Failed to capture frame")
                    continue

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                height, width = frame.shape[:2]
                bed_width = (3 * width // 4 - width // 4) // 2  # Half of original width
                bed_x1 = width // 2 - bed_width // 2
                bed_x2 = width // 2 + bed_width // 2
                bed_y1, bed_y2 = 0, height

                cv2.rectangle(frame, (bed_x1, bed_y1), (bed_x2, bed_y2), (0, 0, 255), 2)
                cv2.putText(frame, "Bed", (bed_x1, bed_y1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

                pose_results = pose.process(rgb_frame)
                mqttDataMP = None

                if pose_results.pose_landmarks:
                    mp_drawing.draw_landmarks(frame, pose_results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
                    state_mediapipe = classify_patient_state(pose_results.pose_landmarks.landmark, frame.shape)

                    left_hip = pose_results.pose_landmarks.landmark[mp_pose.PoseLandmark.LEFT_HIP]
                    right_hip = pose_results.pose_landmarks.landmark[mp_pose.PoseLandmark.RIGHT_HIP]
                    left_hip_x, left_hip_y = left_hip.x * width, left_hip.y * height
                    right_hip_x, right_hip_y = right_hip.x * width, right_hip.y * height

                    if (bed_x1 < left_hip_x < bed_x2 and bed_y1 < left_hip_y < bed_y2) or \
                       (bed_x1 < right_hip_x < bed_x2 and bed_y1 < right_hip_y < bed_y2):
                        if state_mediapipe == "Standing":
                            state_mediapipe = "Laying Down"

                    if state_mediapipe == "Laying Down":
                        if not (bed_x1 < left_hip_x < bed_x2 and bed_y1 < left_hip_y < bed_y2) and \
                           not (bed_x1 < right_hip_x < bed_x2 and bed_y1 < right_hip_y < bed_y2):
                            state_mediapipe = "Fallen out of bed"

                    state_opencv = "Standing" if detect_upper_body(frame) else "Sitting"

                    if state_mediapipe == "Laying Down":
                        label = f"status:\nM: {state_mediapipe}\nOCV: N/A"
                        color = (0, 255, 0)
                    elif state_mediapipe == state_opencv:
                        label = f"status:\nM: {state_mediapipe}\nOCV: {state_opencv}"
                        color = (0, 255, 0)
                    else:
                        label = f"status:\nM: {state_mediapipe}\nOCV: {state_opencv}"
                        color = (0, 0, 255)

                    y_offset = 50
                    for line in label.split('\n'):
                        cv2.putText(frame, line, (50, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                        y_offset += 20

                    mqttDataMP = state_mediapipe

                if mqttDataMP == "Fallen out of bed":
                    mqtt_data = {
                        "timestamp": datetime.now().isoformat(),
                        "mediapipe_state": mqttDataMP,
                        "source": "video",
                    }
                    executor.submit(client.publish, MQTT_TOPIC, json.dumps(mqtt_data), 2)
                    print(f"Fall alert sent via MQTT: State={mqttDataMP}")

                if sio.connected:
                    _, jpeg = cv2.imencode('.jpg', frame)
                    encoded_frame = base64.b64encode(jpeg).decode('utf-8')
                    executor.submit(sio.emit, 'video_frame', encoded_frame)               

            except Exception as e:
                print(f"Error processing frame: {e}")
                continue

        else:
            if cap is not None:
                cap.release()
                cap = None
                if sio.connected:
                    sio.disconnect()
                print("Camera deactivated")
            time.sleep(1)

if __name__ == "__main__":
    generate_frames()
