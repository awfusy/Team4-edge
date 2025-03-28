from gpiozero import DistanceSensor
from time import sleep, time
import paho.mqtt.client as mqtt
import json
from datetime import datetime

# MQTT Configuration
mqtt_broker = "localhost"  # Change this to your broker address
mqtt_port = 1883

# Create MQTT client
client = mqtt.Client()
client.connect(mqtt_broker, mqtt_port, 60)
client.loop_start() 

mqtt_topic_distance = "proximity/alert"

# Initialize 3 ultrasonic sensors
ultrasonic1 = DistanceSensor(echo=17, trigger=4)
ultrasonic2 = DistanceSensor(echo=27, trigger=22)
ultrasonic3 = DistanceSensor(echo=5, trigger=6)
ultrasonic4 = DistanceSensor(echo=26, trigger=19)

captured = False
last_capture_time = 0
capture_interval = 5  # Minimum time between captures (in seconds)

while True:
    # Get distance from all sensors
    distance1 = round(ultrasonic1.distance * 100, 2)  # Convert to cm and round
    distance2 = round(ultrasonic2.distance * 100, 2)
    distance3 = round(ultrasonic3.distance * 100, 2)
    distance4 = round(ultrasonic4.distance * 100, 2)
    patient_on_bed = not (distance1 >= 50 and distance2 >= 50 and distance3 >= 50 and distance4>=50)  # or distance4 > 10)

    # Print distances for monitoring
    print(f"Distance1: {distance1:.2f} cm")
    print(f"Distance2: {distance2:.2f} cm")
    print(f"Distance3: {distance3:.2f} cm")
    print(f"Distance4: {distance4:.2f} cm")
    print(f"Patient on bed: {patient_on_bed}")

    # Create a dictionary with all sensor distances
    sensor_data = {
        "out_of_bed": not patient_on_bed,
        "distance": [distance1, distance2, distance3, distance4],
        "timestamp": datetime.now().isoformat(),
        "source": "proximity"
    }

    
    client.publish(mqtt_topic_distance, json.dumps(sensor_data),qos=2)

                

    sleep(1)  # Shorter delay for better responsiveness

