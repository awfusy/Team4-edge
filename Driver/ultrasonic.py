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
previous_readings = {
    "Head sensor": None,
    "Foot sensor": None,
    "Side sensor 1": None,
    "Side sensor 2": None
}
stale_counters = {
    "Head sensor": 0,
    "Foot sensor": 0,
    "Side sensor 1": 0,
    "Side sensor 2": 0
}
STALE_LIMIT = 5  # Define your stale threshold
MIN_DELTA = 0.001  # Define your minimum change threshold

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
    """
    Advanced distance reading with multi-layered staleness and error detection.
    
    Improved detection strategies:
    1. Invalid reading checks
    2. Stale reading detection
    3. Variability analysis
    4. Contextual error handling
    """
    global previous_readings, stale_counters
    try:
        # Step 1: Basic sensor reading validation
        distance = sensor.distance
        
        # Comprehensive invalid reading checks
        if (
            distance is None or 
            distance > 2.0 or 
            distance < 0 or 
            not isinstance(distance, (int, float))
        ):
            print(f"Warning: {sensor_name} reading invalid: {distance}")
            stale_counters[sensor_name] += 1
            
            # Extended error tracking
            if stale_counters[sensor_name] >= STALE_LIMIT:
                print(f"Critical: {sensor_name} consistently producing invalid readings.")
                return ERROR_THRESHOLD
            
            return ERROR_THRESHOLD
        
        # Step 2: Stale reading detection with enhanced logic
        prev = previous_readings.get(sensor_name)
        
        # Multi-dimensional staleness check
        if prev is not None:
            # Absolute value check
            absolute_change = abs(distance - prev)
            
            # Relative change check (percentage-based)
            relative_change = abs(distance - prev) / max(abs(prev), 1e-5) * 100
            
            # Combined staleness detection
            if (
                absolute_change < MIN_DELTA or 
                relative_change < 0.1  # Less than 0.1% change
            ):
                stale_counters[sensor_name] += 1
            else:
                # Reset counter on significant change
                stale_counters[sensor_name] = 0
        
        # Step 3: Stale reading threshold check
        if stale_counters[sensor_name] >= STALE_LIMIT:
            print(f"Error: {sensor_name} appears to be stuck (stale reading).")
            
            # Additional diagnostic information
            print(f"Last valid reading: {prev}")
            print(f"Current reading: {distance}")
            
            return ERROR_THRESHOLD
        
        # Step 4: Update tracking
        previous_readings[sensor_name] = distance
        
        # Reset stale counter for successful reading
        stale_counters[sensor_name] = 0
        
        return distance
    
    except Exception as e:
        # Comprehensive error logging
        print(f"Unexpected error in {sensor_name}: {e}")
        
        # Increment error counter
        stale_counters[sensor_name] += 1
        
        # Check if repeated errors suggest a systemic issue
        if stale_counters[sensor_name] >= STALE_LIMIT:
            print(f"Critical: {sensor_name} experiencing persistent read failures.")
        
        return ERROR_THRESHOLD
    
def check_bed_occupancy(*readings):
    """Determine occupancy based on valid sensor readings only."""
    # Filter out error readings
    valid_readings = [d for d in readings if d != ERROR_THRESHOLD]
    
    if not valid_readings:
        # If all sensors are in error, decide on a safe default (or flag as error)
        return False  # or you might want to flag it separately
    
    # Use majority logic: if most valid readings indicate occupancy, then return True
    occupied_count = sum(1 for d in valid_readings if d < DISTANCE_THRESHOLD)
    
    # For instance, occupancy is true if more than half of the valid readings indicate an object is within the threshold
    return occupied_count >= (len(valid_readings) / 2)


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
                    
                sensor_readings = [d1, d2, d3, d4]
                error_count_this_cycle = sum(1 for d in sensor_readings if d == ERROR_THRESHOLD)

                if error_count_this_cycle >= MAX_CONSECUTIVE_ERRORS:
                    error_count += 1  # Increase only when multiple sensors fail
                    print(f"Sensor error detected (count: {error_count}), {error_count_this_cycle} sensors reporting errors")

                    if error_count >= MAX_CONSECUTIVE_ERRORS:
                        alert_data = {
                            "error": "Sensor malfunction detected",
                            "timestamp": datetime.now().isoformat(),
                            "source": "proximity"
                        }
                        try:
                            client.publish("proximity/error", json.dumps(alert_data), qos=0)
                        except:
                            print("Failed to send error alert")

                        if restart_sensors():
                            error_count = 0  # Reset after successful restart
                        sleep(SENSOR_ERROR_DELAY)
                        continue  # Skip this cycle

                    sleep(SENSOR_ERROR_DELAY)
                    continue  # Skip this cycle

                else:
                    error_count = 0  # Reset if the system recovers

                # Filter valid sensor readings before occupancy check
                valid_readings = [d for d in sensor_readings if d != ERROR_THRESHOLD]
                patient_on_bed = check_bed_occupancy(*valid_readings)

                distances_cm = [d * 100 for d in valid_readings]

                sensor_data = {
                    "out_of_bed": not patient_on_bed,
                    "distances": distances_cm,
                    "timestamp": datetime.now().isoformat(),
                    "source": "proximity"
                }

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

