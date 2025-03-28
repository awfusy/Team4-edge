from gpiozero import DistanceSensor
from time import sleep, time
from libcamera import Transform
import paho.mqtt.client as mqtt
import json
from datetime import datetime

# MQTT Configuration
mqtt_broker = "localhost"  # Change this to your broker address
mqtt_port = 1883

# Create MQTT client
client = mqtt.Client()
client.connect(mqtt_broker, mqtt_port, 60)

mqtt_topic_distance = "proximity/alert"


# Initialize 3 ultrasonic sensors
ultrasonic1 = DistanceSensor(echo=17, trigger=4)
ultrasonic2 = DistanceSensor(echo=27, trigger=22)
ultrasonic3 = DistanceSensor(echo=5, trigger=6)
# ultrasonic4 = DistanceSensor(echo=13, trigger=19)

captured = False
last_capture_time = 0
capture_interval = 5  # Minimum time between captures (in seconds)

while True:
    # Get distance from all sensors
    distance1 = ultrasonic1.distance * 100  # Convert to cm
    distance2 = ultrasonic2.distance * 100
    distance3 = ultrasonic3.distance * 100
    # distance4 = ultrasonic4.distance * 100
    patient_on_bed = not (distance1 >= 10 or distance2 >= 10 or distance3 >= 10)  # or distance4 > 10)

    # Print distances for monitoring
    print(f"Distance1: {distance1:.2f} cm")
    print(f"Distance2: {distance2:.2f} cm")
    print(f"Distance3: {distance3:.2f} cm")
    # print(f"Distance4: {distance4:.2f} cm")
    print(f"Patient on bed: {patient_on_bed}")

    # Create a dictionary with all sensor distances
    sensor_data = {
        # "sensor4": distance4,
        "out_of_bed": not patient_on_bed,
        "distances": [distance1, distance2, distance3],
        "timestamp": datetime.now().isoformat(),
        "source": "proximity"
    }


    client.publish(mqtt_topic_distance, json.dumps(sensor_data), qos=2)
    sleep(1)  # Shorter delay for better responsiveness

