from gpiozero import DistanceSensor
from time import sleep, time
import paho.mqtt.client as mqtt
import json
from datetime import datetime

# Configuration
mqtt_broker = "192.168.211.254"
mqtt_port = 1883
DISTANCE_THRESHOLD = 0.50  # 10cm in meters
PUBLISH_INTERVAL = 2.0    # Seconds between readings
MAX_CONSECUTIVE_ERRORS = 3  # Number of errors before attempting restart
SENSOR_ERROR_DELAY = 2.0    # Seconds to wait after sensor error
ERROR_THRESHOLD = float('inf')  # Value returned on error

# Initialize MQTT client
client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    """MQTT Connection Callback"""
    connection_codes = {
        0: "Connected successfully",
        1: "Incorrect protocol version",
        2: "Invalid client identifier",
        3: "Server unavailable",
        4: "Bad username or password",
        5: "Not authorized"
    }
    print(f"Connected with result code: {connection_codes.get(rc, 'Unknown error')}")

def on_disconnect(client, userdata, rc):
    """Handle disconnections"""
    if rc != 0:
        print(f"Unexpected disconnection. Code: {rc}")
        # Try to reconnect
        try:
            client.reconnect()
        except Exception as e:
            print(f"Reconnection failed: {e}")

def publish_data(sensor_data):
    """Send data to MQTT broker"""
    try:
        # Store result of publish
        result = client.publish("proximity/alert", json.dumps(sensor_data),qos=2)
        
        # Wait for publish to complete
        result.wait_for_publish()
        
        if result.is_published():
            print(f"â Data successfully published")
            return True
        else:
            print(f"! Data may not have been delivered")
            return False
            
    except Exception as e:
        print(f"â Failed to send MQTT message: {e}")
        return False

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
    return not((d1 < DISTANCE_THRESHOLD) and (d2 < DISTANCE_THRESHOLD) and (d3 < DISTANCE_THRESHOLD) and (d4 < DISTANCE_THRESHOLD))


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
            print(f"Failed to connect to MQTT broker: {e}")
            # Don't exit, let it try to reconnect

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
                    
                    # Check for sensor errors and attempt restart if needed
                    if d1 == ERROR_THRESHOLD or d2 == ERROR_THRESHOLD or d3 == ERROR_THRESHOLD or d4 == ERROR_THRESHOLD:
                        error_count += 1
                        print(f"Sensor error detected (count: {error_count})")
                        
                        if error_count >= MAX_CONSECUTIVE_ERRORS:
                            if restart_sensors():
                                error_count = 0
                            sleep(SENSOR_ERROR_DELAY)
                            continue
                        
                        sleep(SENSOR_ERROR_DELAY)
                        continue
                    
                    # Reset error count if successful
                    error_count = 0
                    
                    out_of_bed = check_bed_occupancy(d1, d2, d3, d4)
                    distances_cm = [round(d * 100, 2) for d in [d1, d2, d3, d4]]
                    timestamp = datetime.now().isoformat()
                    sensor_data = {
                        "out_of_bed": out_of_bed,
                        "distances": distances_cm,
                        "timestamp": timestamp,
                        "source": "proximity"
                    }

                    # Print sensor readings immediately
                    print(f"Distances: {[f'{d:.1f}' for d in distances_cm]} cm")
                    print(f"Out of bed: {out_of_bed}")
                    print(f"Timestamp: {timestamp}")

                    # Then attempt to publish
                    if publish_data(sensor_data):
                        last_publish_time = current_time
                    else:
                        print("! Will retry on next interval")
                        # Don't update last_publish_time so it retries immediately next loop

                sleep(0.1)

            except Exception as e:
                print(f"Loop error: {e}")
                sleep(0.5)

    except KeyboardInterrupt:
        print("\nStopping gracefully...")
    finally:
        print("Cleaning up...")
        try:
            for sensor in [ultrasonic1, ultrasonic2, ultrasonic3, ultrasonic4]:
                sensor.close()
        except:
            pass
        try:
            client.loop_stop()
            client.disconnect()
        except:
            pass



