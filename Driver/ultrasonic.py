from gpiozero import DistanceSensor
from time import sleep, time
import paho.mqtt.client as mqtt
import json
from datetime import datetime

# Configuration
mqtt_broker = "localhost"
mqtt_port = 1883
DISTANCE_THRESHOLD = 0.10  # 10cm in meters
PUBLISH_INTERVAL = 1.0    # Seconds between readings
MAX_SENSOR_TIMEOUT = 1.0  # Maximum time to wait for sensor reading
MAX_CONSECUTIVE_ERRORS = 3  # Number of errors before attempting restart
SENSOR_ERROR_DELAY = 2.0    # Seconds to wait after sensor error
ERROR_THRESHOLD = float('inf')  # Value returned on error

# Initialize MQTT
client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")

def on_disconnect(client, userdata, rc):
    print(f"Disconnected with result code {rc}")

client.on_connect = on_connect
client.on_disconnect = on_disconnect

# Initialize sensors with timeout
try:
    ultrasonic1 = DistanceSensor(echo=17, trigger=4)   
    ultrasonic2 = DistanceSensor(echo=27, trigger=22)  
    ultrasonic3 = DistanceSensor(echo=5, trigger=6) 
    ultrasonic4 = DistanceSensor(echo=26, trigger=19)     
except Exception as e:
    print(f"Failed to initialize sensors: {e}")
    exit(1)

def get_safe_distance(sensor, sensor_name):
    """Get distance with improved error handling"""
    try:
        distance = sensor.distance
        if distance is None or distance > 2.0:  # Sanity check
            print(f"Warning: {sensor_name} reading invalid: {distance}m")
            return ERROR_THRESHOLD
        return distance
    except Exception as e:
        print(f"Error: {sensor_name} read failed: {e}")
        return ERROR_THRESHOLD

def check_bed_occupancy(d1, d2, d3, d4):
    """Simple bed occupancy check using raw meter values"""
    return all(d < DISTANCE_THRESHOLD for d in [d1, d2, d3, d4])

def restart_sensors():
    """Attempt to restart sensors"""
    global ultrasonic1, ultrasonic2, ultrasonic3, ultrasonic4
    print("Attempting to restart sensors...")
    try:
        # Close existing sensors
        for sensor in [ultrasonic1, ultrasonic2, ultrasonic3, ultrasonic4]:
            try:
                sensor.close()
            except:
                pass
        
        # Reinitialize sensors
        ultrasonic1 = DistanceSensor(echo=17, trigger=4)
        ultrasonic2 = DistanceSensor(echo=27, trigger=22)
        ultrasonic3 = DistanceSensor(echo=5, trigger=6)
        ultrasonic4 = DistanceSensor(echo=26, trigger=19)     
        print("Sensors restarted successfully")
        return True
    except Exception as e:
        print(f"Failed to restart sensors: {e}")
        return False

if __name__ == "__main__":
    try:
        # Connect to MQTT broker
        try:
            client.connect(mqtt_broker, mqtt_port, 60)
            client.loop_start()
        except Exception as e:
            print(f"MQTT connection failed: {e}")
            exit(1)

        last_publish_time = 0
        error_count = 0

        while True:
            try:
                current_time = time()
                
                if current_time - last_publish_time >= PUBLISH_INTERVAL:
                    # Get raw distances with improved error handling
                    d1 = get_safe_distance(ultrasonic1, "Head sensor")
                    d2 = get_safe_distance(ultrasonic2, "Foot sensor")
                    d3 = get_safe_distance(ultrasonic3, "Side sensor")
                    d4 = get_safe_distance(ultrasonic4, "Side sensor")
                    
                    # Check for sensor errors
                    if d1 == ERROR_THRESHOLD or d2 == ERROR_THRESHOLD or d3 == ERROR_THRESHOLD or d4 == ERROR_THRESHOLD:
                        error_count += 1
                        print(f"Sensor error detected (count: {error_count})")
                        
                        if error_count >= MAX_CONSECUTIVE_ERRORS:
                            # Alert about sensor issues
                            alert_data = {
                                "error": "Sensor malfunction detected",
                                "timestamp": datetime.now().isoformat(),
                                "source": "proximity"
                            }
                            try:
                                client.publish("proximity/error", json.dumps(alert_data), qos=0)
                            except:
                                print("Failed to send error alert")

                            # Attempt restart
                            if restart_sensors():
                                error_count = 0
                            sleep(SENSOR_ERROR_DELAY)
                            continue
                        
                        sleep(SENSOR_ERROR_DELAY)
                        continue
                    
                    # Reset error count if successful
                    error_count = 0
                    
                    patient_on_bed = check_bed_occupancy(d1, d2, d3 , d4)
                    distances_cm = [d * 100 for d in [d1, d2, d3, d4]]
                    
                    sensor_data = {
                        "out_of_bed": not patient_on_bed,
                        "distances": distances_cm,
                        "timestamp": datetime.now().isoformat(),
                        "source": "proximity"
                    }

                    # Try to publish
                    try:
                        client.publish("proximity/alert", json.dumps(sensor_data), qos=1)
                        print(f"Distances: {[f'{d:.1f}' for d in distances_cm]} cm")
                        print(f"Patient on bed: {patient_on_bed}")
                        last_publish_time = current_time
                    except Exception as e:
                        print(f"Publish error: {e}")

                sleep(0.1)

            except Exception as e:
                print(f"Loop error: {e}")
                sleep(0.5)

    except KeyboardInterrupt:
        print("\nStopping gracefully...")
    finally:
        print("Cleaning up...")
        try:
            ultrasonic1.close()
            ultrasonic2.close()
            ultrasonic3.close()
            ultrasonic4.close() 
        except:
            pass
        try:
            client.loop_stop()
            client.disconnect()
        except:
            pass

