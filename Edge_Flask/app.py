from flask import Flask, render_template, Response, jsonify
import cv2
import paho.mqtt.client as mqtt
import json
from datetime import datetime
from collections import deque

app = Flask(__name__)

# Store latest data for dashboard with larger capacity
dashboard_data = {
    'alerts': {
        'high_priority': deque(maxlen=100),    # Critical alerts (falls, emergencies)
        'medium_priority': deque(maxlen=200),   # Important but non-critical (voice commands)
        'low_priority': deque(maxlen=500)       # Regular updates (proximity data)
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
    """Smart alert handling based on type and priority"""
    priority = alert_data.get('priority', 'LOW').upper()
    
    # Update current states based on source
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

    # Store in appropriate queue based on priority
    if priority == 'HIGH':
        dashboard_data['alerts']['high_priority'].appendleft(alert_data)
    elif priority == 'MEDIUM':
        dashboard_data['alerts']['medium_priority'].appendleft(alert_data)
    else:  # LOW priority
        dashboard_data['alerts']['low_priority'].appendleft(alert_data)

# MQTT callback
def on_message(client, userdata, message):
    """Handle incoming MQTT messages from central hub"""
    try:
        payload = json.loads(message.payload.decode('utf-8'))
        if message.topic == 'nurse/dashboard':
            add_alert(payload)
    except Exception as e:
        print(f"Error processing MQTT message: {e}")

# Initialize MQTT client
mqtt_client = mqtt.Client()
mqtt_client.on_message = on_message

try:
    mqtt_client.connect("localhost", 1883, 60)
    mqtt_client.subscribe("nurse/dashboard", qos=2)
    mqtt_client.loop_start()
except Exception as e:
    print(f"Failed to connect to MQTT broker: {e}")

# Video streaming
def generate_frames():
    camera = cv2.VideoCapture(0)
    while True:
        success, frame = camera.read()
        if not success:
            break
        else:
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

# Flask routes
@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html', 
                         data=dashboard_data,
                         room_number=dashboard_data['room_number'])

@app.route('/api/status')
def get_status():
    """Get current patient status and states"""
    return jsonify({
        'patient_status': dashboard_data['patient_status'],
        'current_states': dashboard_data['current_states'],
        'room_number': dashboard_data['room_number']
    })

@app.route('/api/alerts')
def get_alerts():
    """Get alerts with optional filtering"""
    priority = request.args.get('priority', 'all').lower()
    
    if priority == 'high':
        alerts = list(dashboard_data['alerts']['high_priority'])
    elif priority == 'medium':
        alerts = list(dashboard_data['alerts']['medium_priority'])
    elif priority == 'low':
        alerts = list(dashboard_data['alerts']['low_priority'])
    else:
        # Combine all alerts, maintaining time order
        all_alerts = []
        for queue in ['high_priority', 'medium_priority', 'low_priority']:
            all_alerts.extend(list(dashboard_data['alerts'][queue]))
        alerts = sorted(all_alerts, key=lambda x: x['timestamp'], reverse=True)
    
    return jsonify(alerts)

@app.route('/api/alerts/acknowledge/<int:alert_index>', methods=['POST'])
def acknowledge_alert(alert_index):
    """Mark alert as acknowledged"""
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
    """Video streaming route"""
    return Response(generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/notifications')
def notifications():
    """Notifications page"""
    return render_template('notifications.html',
                         alerts=list(dashboard_data['alerts']['high_priority']))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
