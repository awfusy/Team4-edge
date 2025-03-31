import eventlet

# Monkey patching must come first to enable non-blocking I/O
eventlet.monkey_patch()

from collections import deque
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import json
import paho.mqtt.client as mqtt  # MQTT temporarily disabled
from datetime import datetime

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins='*')

# Store latest frame from WebSocket camera
latest_frame = ""

# List to store received notifications (for rendering on page load)
notifications = []

# Store latest data for dashboard with larger capacity
dashboard_data = {
    'alerts': {
        'high_priority': deque(maxlen=100),
        'medium_priority': deque(maxlen=200),
        'low_priority': deque(maxlen=500)
    },
    'current_states': {
        'video': {
            'details': None,
            'last_updated': None
        },
        'audio': {
            'details': None,
            'confidence': None,
            'last_detection': None
        },
        'proximity': {
            'distances': [],
            'out_of_bed': False,
            'last_reading': None
        }
    },
    'patient_status': 'Normal',
    'room_number': '101'
}

# Helper function to add alerts into dashboard_data structure
def add_alert(alert_data):
    priority = alert_data.get('priority', 'LOW').upper()
    source = alert_data.get('source', '')
    # Update current sensor state
    if source == 'video':
        dashboard_data['current_states']['video'].update({
            'details': alert_data.get('details'),
            'last_updated': alert_data.get('timestamp')
        })
    elif source == 'audio':
        dashboard_data['current_states']['audio'].update({
            'details': alert_data.get('details'),
            'confidence': alert_data.get('confidence'),
            'last_detection': alert_data.get('timestamp')
        })
    elif source == 'proximity':
        dashboard_data['current_states']['proximity'].update({
            'distances': alert_data.get('distances', []),
            'out_of_bed': alert_data.get('out_of_bed', False),
            'last_reading': alert_data.get('timestamp')
        })

    # Add alert to appropriate queue
    if priority == 'HIGH':
        dashboard_data['alerts']['high_priority'].appendleft(alert_data)
    elif priority == 'MEDIUM':
        dashboard_data['alerts']['medium_priority'].appendleft(alert_data)
    else:
        dashboard_data['alerts']['low_priority'].appendleft(alert_data)

# MQTT client setup
mqtt_client = mqtt.Client()


patient_names = ["Alice Tan"]
room_numbers = ["Room 101"]

# MQTT connection callback
def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT broker with code:", rc)
    client.subscribe("nurse/dashboard")

# MQTT message handling
def on_message(client, userdata, msg):
    try:
        raw = json.loads(msg.payload.decode())
        print(f"MQTT message received on topic '{msg.topic}': {raw}")

        # Extract basic alert data
        timestamp = raw.get("timestamp", "")
        alert_type = raw.get("alert_type", "Unknown")
        source = raw.get("source", "Unknown")
        details = raw.get("details", "No details provided.")
        priority = raw.get("priority", "MEDIUM")
        distances = raw.get("distances", [])

        # Flag handling for camera activation to control dashboard live streaming
        if source.lower() == 'camera_activation':
            activate = raw.get("activate", False)
            socketio.emit('camera_activation', {
                'activate': activate
            })
            print(f"Camera activation set to {activate}")
            return

        # Display logic
        patient_name = patient_names[0]
        room_no = room_numbers[0]  
        in_bed = "No" if "out" in alert_type.lower() or "fall" in alert_type.lower() else "Yes"

        formatted_time = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%f").strftime("%Y-%m-%d %H:%M:%S")

        # Message format for frontend
        message = (
    f"👤 Patient Name        : {patient_name}\n"
    f"📡 Source              : {source.capitalize()}\n"
    f"🏥 Room No             : {room_no}\n"
    f"⚠️ Emergency Level     : {priority}\n"
    f"🩺 Patient Condition   : {details}\n"
    f"🛏️ Still in Bed        : {in_bed}\n"
)
        
        # Add distance if source is proximity
        if source.lower() == "proximity":
            message += f"📏 Distance            : {distances}\n"

        message += f"⏰ Timestamp           : {formatted_time}"

        # Emit notification to frontend
        socketio.emit('new_notification', {
            "message": message,
            "priority": priority,
            "timestamp": formatted_time
        })
        print("Notification emitted to frontend")

    except Exception as e:
        print("MQTT error:", e)

# MQTT binding
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# Connect to broker
try:
    mqtt_client.connect("192.168.61.254", 1883, 60)
    mqtt_client.loop_start()
except Exception as e:
    print(f"Failed to connect to MQTT broker: {e}")

# Flask Routes
@app.route('/')
def index():
    return render_template('dashboard.html', 
                           data=dashboard_data,
                           room_number=dashboard_data['room_number'])

# Socket.IO handlers
@socketio.on('video_frame')
def handle_video_frame(data):
    global latest_frame
    latest_frame = data
    print("Received video_frame and broadcasting update_frame")
    socketio.emit('update_frame', latest_frame)

@socketio.on('request_latest_frame')
def handle_frame_request():
    if latest_frame:
        emit('update_frame', latest_frame)
    else:
        print("No frame available to send")

@socketio.on('connect')
def test_connect():
    print("Client connected")

# Run the app
if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

