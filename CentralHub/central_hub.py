import paho.mqtt.client as mqtt
import json
import logging
from datetime import datetime
import time

class SimplifiedCentralHub:
    def __init__(self, broker_address='localhost', broker_port=1883, reconnect_delay=3, publish_retry_delay=3):
        # MQTT Client Setup with clean_session=False for reliability
        self.client_id = "CentralHub"
        self.client = mqtt.Client(client_id=self.client_id, clean_session=False)
        
        # Broker Configuration
        self.broker_address = broker_address
        self.broker_port = broker_port
        self.reconnect_delay = reconnect_delay  # Configurable reconnect delay
        self.publish_retry_delay = publish_retry_delay
        
        # Setup Logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s: %(message)s',
            handlers=[
                logging.FileHandler('central_hub.log'),
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Topics Configuration
        self.topics = {
            'audio/emergency': 2,     # Audio alerts from wake word
            'video/emergency': 2,     # Video alerts from fall detection
            'proximity/alert': 1,     # Proximity alerts from ultrasonic
        }

        # Connection state tracking
        self.connection_active = False

    def on_connect(self, client, userdata, flags, rc):
        """MQTT Connection Callback"""
        connection_codes = {
            0: "Connected successfully",
            1: "Incorrect protocol version",
            2: "Invalid client identifier",
            3: "Server unavailable",
            4: "Bad username or password",
            5: "Not authorized"
        }
        
        if rc != 0:
            print(f"Connection failed")  # Simple console feedback
            self.connection_active = False
            self.logger.error(f"Connection failed: {connection_codes.get(rc, 'Unknown error')}")
            return

        print(f"Connected to MQTT Broker: {self.broker_address}")  # Simple console feedback
        self.connection_active = True
        self.logger.info(f"Connected to MQTT Broker {self.broker_address}")
        
        # Subscribe to all topics
        for topic, qos in self.topics.items():
            try:
                result, mid = self.client.subscribe(topic, qos)
                if result == mqtt.MQTT_ERR_SUCCESS:
                    print(f"Subscribed to {topic}")  # Simple console feedback
                    self.logger.info(f"Subscribed to {topic} with QoS {qos}")
                else:
                    self.logger.error(f"Failed to subscribe to {topic}")
            except Exception as e:
                self.logger.error(f"Subscription error for {topic}: {e}")

    def on_disconnect(self, client, userdata, rc):
        """Handle disconnections"""
        disconnect_time = datetime.now().isoformat()
        self.connection_active = False
        
        if rc != 0:
            print(f"Unexpected disconnection at {disconnect_time}")  # Immediate feedback
            self.logger.warning(f"Unexpected disconnection at {disconnect_time}. Attempting to reconnect...")
            self.reconnect_with_fixed_delay()

    def reconnect_with_fixed_delay(self):
        """Simple reconnection with fixed delay"""
        attempt = 1
        while not self.connection_active:
            try:
                print(f"Reconnection attempt {attempt}")  # Immediate feedback
                self.client.reconnect()
                break
            except Exception as e:
                self.logger.error(f"Reconnection attempt {attempt} failed: {e}")
                attempt += 1
                time.sleep(self.reconnect_delay)

    def publish_with_retry(self, topic, payload, max_retries=3):
        """Publish messages with retry mechanism"""
        for attempt in range(max_retries):
            try:
                if not self.connection_active:
                    print(f"Not connected to broker. Attempt {attempt + 1}/{max_retries}")  
                    self.logger.error("Not connected to broker")
                    time.sleep(self.publish_retry_delay)
                    continue
                
                self.client.publish(topic, json.dumps(payload), qos=1)
                return  # If publish didn't raise an exception, we're done
            
            except Exception as e:
                print(f"Publish error on attempt {attempt + 1}: {e}")
                self.logger.error(f"Publish error on attempt {attempt + 1}: {e}")
                time.sleep(self.publish_retry_delay)
        
        self.logger.error(f"Failed to publish to {topic} after {max_retries} attempts")

    def on_message(self, client, userdata, message):
        """Message Handler"""
        try:
            payload = json.loads(message.payload.decode('utf-8'))
            
            # Use dict for handler mapping
            handlers = {
                "audio/emergency": self.handle_audio_alert,
                "video/emergency": self.handle_fall_alert,
                "proximity/alert": self.handle_proximity_alert
            }
            
            handler = handlers.get(message.topic)
            if handler:
                handler(payload)
                print(f"Handled {message.topic}")  # Simple console feedback
        
        except json.JSONDecodeError:
            print(f"Invalid JSON on {message.topic}")
            self.logger.error(f"Invalid JSON on topic {message.topic}")
        except Exception as e:
            self.logger.error(f"Message processing error: {e}")


    def handle_audio_alert(self, payload):
        """Process Audio Alerts"""
        phrase = payload.get('phrase', '')
        print(f"Audio Alert: {phrase}")  # Simple console feedback
        priority = 'HIGH' if payload.get('alert_type') in ['Urgent Assistance', 'Pain/Discomfort'] else 'MEDIUM'
        
        alert_data = {
            'timestamp': payload.get('timestamp', datetime.now().isoformat()),
            'alert_type': payload.get('alert_type'),
            'confidence': payload.get('confidence'),
            'source': payload.get('source', 'audio'),
            'details': f"Detected: {payload.get('phrase', '')}",
            'priority': priority
        }
        
        self.client.publish('nurse/dashboard', json.dumps(alert_data), qos=2)
        self.logger.info(f"Audio Alert Sent: {alert_data}")

    def handle_fall_alert(self, payload):
        """Process Fall Detection Alerts"""
        try:
            mediapipe_state = payload.get('mediapipe_state')
            opencv_state = payload.get('opencv_state')
            
            if mediapipe_state == "Fallen out of bed" or opencv_state == "Fallen out of bed":
                print(f"FALL DETECTED: {mediapipe_state}")  # Simple console feedback
                alert_data = {
                    'timestamp': payload.get('timestamp', datetime.now().isoformat()),
                    'alert_type': 'FALL_DETECTED',
                    'source': payload.get('source', 'video'),
                    'details': f"Patient fallen out of bed (MediaPipe: {mediapipe_state})",
                    'priority': 'HIGH'
                }
                
                self.client.publish('nurse/dashboard', json.dumps(alert_data), qos=2)
                self.logger.info(f"Fall Alert Sent: {alert_data}")
        
        except Exception as e:
            self.logger.error(f"Fall detection error: {e}")

    def handle_proximity_alert(self, payload):
        """Process Proximity Alerts"""
        try:
            out_of_bed = payload.get('out_of_bed', False)
            distances = payload.get('distances', [])
            timestamp = payload.get('timestamp', datetime.now().isoformat())
            source = payload.get('source', 'proximity')
            
            # Print simple status
            status = "OUT OF BED" if out_of_bed else "In bed"
            print(f"Patient Status: {status} - Distances: {distances}")

            # Always send proximity data
            proximity_data = {
                'timestamp': timestamp,
                'alert_type': 'PROXIMITY_DATA',
                'source': 'proximity',
                'distances': distances,
                'priority': 'LOW'
            }
            self.publish_with_retry('nurse/dashboard', proximity_data)
            
            # If patient out of bed
            if out_of_bed:
                # Activate video
                video_alert = {'activate': True}
                self.client.publish('video/monitor', json.dumps(video_alert), qos=2)
                
                # Send alert
                alert_data = {
                    'timestamp': timestamp,
                    'alert_type': 'PATIENT_OUT_OF_BED',
                    'source': source,
                    'distances': distances,
                    'priority': 'HIGH'
                }
                self.client.publish('nurse/dashboard', json.dumps(alert_data), qos=2)
            else:
                # Deactivate video
                video_alert = {'activate': False}
                self.client.publish('video/monitor', json.dumps(video_alert), qos=2)
                
        except Exception as e:
            print(f"Proximity alert error: {e}")  # Immediate console feedback
            self.logger.error(f"Proximity alert error: {e}")

    def start(self):
        """Start the Central Hub"""
        try:
            self.client.on_connect = self.on_connect
            self.client.on_message = self.on_message
            self.client.on_disconnect = self.on_disconnect
            
            # Enable MQTT keepalive
            self.client.keepalive = 60
            
            # Connect with retry using configured delay
            retry_count = 0
            while retry_count < 3:
                try:
                    self.client.connect(self.broker_address, self.broker_port, 60)
                    break
                except Exception as e:
                    retry_count += 1
                    self.logger.error(f"Connection attempt {retry_count} failed: {e}")
                    if retry_count == 3:
                        raise
                    time.sleep(self.reconnect_delay)  # Use configured delay instead of hardcoded 5
            
            self.client.loop_forever()
            
        except Exception as e:
            self.logger.error(f"Central Hub Error: {e}")
            raise

def main():
    hub = SimplifiedCentralHub()
    try:
        hub.start()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
        hub.client.disconnect()  # Add graceful disconnect
        hub.client.loop_stop()   # Add loop stop
    except Exception as e:
        logging.error(f"Fatal error: {e}")

if __name__ == "__main__":
    main()
