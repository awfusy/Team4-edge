from flask import Flask,render_template,Response
import cv2
from flask_socketio import SocketIO, emit
import json
import threading
import paho.mqtt.client as mqtt
import random

app=Flask(__name__)
camera=cv2.VideoCapture(0)
socketio = SocketIO(app)

# List to store received notifications (for rendering on page load)
notifications = []

def generate_frames():
    while True:           
        # Read the camera frame
        success,frame=camera.read()
        if not success:
            break
        else:
            ret,buffer=cv2.imencode('.jpg',frame)
            frame=buffer.tobytes()

        yield(b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/notification')
def dashboard():
    return render_template("notification.html", notifications=notifications)

@app.route('/video')
def video():
    return Response(generate_frames(),mimetype='multipart/x-mixed-replace; boundary=frame')

# MQTT Setup
mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT broker with code:", rc)
    client.subscribe("nurse/dashboard")

# Sample patient names and room numbers
patient_names = ["Alice Tan", "John Lim", "Maria Gomez", "David Chen", "Nora Ali"]
room_numbers = ["Ward 1A", "Ward 2B", "ICU 3", "Room 4D", "Emergency Room"]

def on_message(client, userdata, msg):
    try:
        raw = json.loads(msg.payload.decode())

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

    except Exception as e:
        print("MQTT error:", e)

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def mqtt_loop():
    mqtt_client.connect("localhost", 1883, 60)
    mqtt_client.loop_forever()

# Start MQTT loop in a separate thread
threading.Thread(target=mqtt_loop).start()

if __name__=="__main__":
    app.run(debug=True)
