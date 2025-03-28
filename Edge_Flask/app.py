import eventlet

# Monkey patching must come first
eventlet.monkey_patch()

from collections import deque
from flask import Flask, render_template, Response, jsonify, request
import cv2
from flask_socketio import SocketIO, emit
import json
import threading
import paho.mqtt.client as mqtt  # MQTT temporarily disabled
import random

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

def add_alert(alert_data):
    priority = alert_data.get('priority', 'LOW').upper()
    source = alert_data.get('source', '')
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

    if priority == 'HIGH':
        dashboard_data['alerts']['high_priority'].appendleft(alert_data)
    elif priority == 'MEDIUM':
        dashboard_data['alerts']['medium_priority'].appendleft(alert_data)
    else:
        dashboard_data['alerts']['low_priority'].appendleft(alert_data)

mqtt_client = mqtt.Client()

patient_names = ["Alice Tan", "John Lim", "Maria Gomez", "David Chen", "Nora Ali"]
room_numbers = ["Ward 1A", "Ward 2B", "ICU 3", "Room 4D", "Emergency Room"]

def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT broker with code:", rc)
    client.subscribe("nurse/dashboard")

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        print(f"📥 MQTT message received on topic '{msg.topic}': {payload}")
        
        raw = json.loads(payload)

        # Debug individual keys (optional)
        print("🧾 Parsed JSON content:")
        for key, value in raw.items():
            print(f"  {key}: {value}")

        notification = {
            "name": random.choice(patient_names),
            "room": random.choice(room_numbers),
            "priority": raw.get("priority", "MEDIUM"),
            "condition": raw.get("alert_type", "Unknown"),
            "in_bed": "No" if "out" in raw.get("alert_type", "").lower() else "Yes",
            "timestamp": raw.get("timestamp", "")
        }
        notifications.append(notification)
        socketio.emit('new_notification', notification)
        add_alert(raw)
    except Exception as e:
        print("MQTT error:", e)

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

try:
    mqtt_client.connect("192.168.211.254", 1883, 60)
    mqtt_client.loop_start()
except Exception as e:
    print(f"Failed to connect to MQTT broker: {e}")


@app.route('/')
def index():
    return render_template('dashboard.html', 
                           data=dashboard_data,
                           room_number=dashboard_data['room_number'])

@app.route('/dashboard_template')
def dash_temp():
    return render_template('dashboard_template.html')

@app.route('/api/status')
def get_status():
    return jsonify({
        'patient_status': dashboard_data['patient_status'],
        'current_states': dashboard_data['current_states'],
        'room_number': dashboard_data['room_number']
    })

@app.route('/api/alerts')
def get_alerts():
    priority = request.args.get('priority', 'all').lower()
    if priority == 'high':
        alerts = list(dashboard_data['alerts']['high_priority'])
    elif priority == 'medium':
        alerts = list(dashboard_data['alerts']['medium_priority'])
    elif priority == 'low':
        alerts = list(dashboard_data['alerts']['low_priority'])
    else:
        all_alerts = []
        for queue in ['high_priority', 'medium_priority', 'low_priority']:
            all_alerts.extend(list(dashboard_data['alerts'][queue]))
        alerts = sorted(all_alerts, key=lambda x: x['timestamp'], reverse=True)
    return jsonify(alerts)

@app.route('/api/alerts/acknowledge/<int:alert_index>', methods=['POST'])
def acknowledge_alert(alert_index):
    try:
        priority = request.json.get('priority', 'high').lower()
        alerts_list = list(dashboard_data['alerts'][f'{priority}_priority'])
        if 0 <= alert_index < len(alerts_list):
            alerts_list[alert_index]['acknowledged'] = True
            dashboard_data['alerts'][f'{priority}_priority'] = deque(alerts_list, 
                maxlen=dashboard_data['alerts'][f'{priority}_priority'].maxlen)
            return jsonify({'success': True})
    except Exception as e:
        print(f"Error acknowledging alert: {e}")
    return jsonify({'success': False}), 400

@app.route('/video_feed')
def video_feed():
    return render_template('video_stream.html')

@socketio.on('video_frame')
def handle_video_frame(data):
    global latest_frame
    latest_frame = data
    socketio.emit('update_frame', latest_frame)

@socketio.on('connect')
def test_connect():
    print("Client connected")

@app.route('/notifications')
def notifications():
    return render_template('notifications.html',
                           alerts=list(dashboard_data['alerts']['high_priority']))

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

