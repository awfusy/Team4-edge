import paho.mqtt.client as mqtt
import json
import logging
from datetime import datetime
import time

class SimplifiedCentralHub:
    def __init__(self, broker_address='192.168.211.254', broker_port=1883, reconnect_delay=3, publish_retry_delay=1):
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
        
        # Topics Configuration with QoS levels
        self.topics = {
            'audio/emergency': 2,     # Audio alerts from wake word
            'video/emergency': 2,     # Video alerts from fall detection
            'proximity/alert': 2,     # Proximity alerts from ultrasonic
        }
        
        # Handler mapping - maps topics to their handler methods
        self.handlers = {
            'proximity/alert': self.handle_proximity_alert,
            'audio/emergency': self.handle_audio_alert,
            'video/emergency': self.handle_fall_alert
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
        
        # First clear any retained messages
        print("Clearing retained messages...")
        for topic in self.topics:
            self.client.publish(topic, "", qos=1, retain=True)
        time.sleep(0.5)  # Small delay to ensure clearing completes
        
        # Then subscribe to topics
        for topic, qos in self.topics.items():
            try:
                result, _ = self.client.subscribe(topic, qos)  # Unpack the tuple
                if result == mqtt.MQTT_ERR_SUCCESS:  # Check result[0]
                    print(f"Subscribed to {topic} with QoS {qos}")  # Simple console feedback
                    self.logger.info(f"Subscribed to {topic} with QoS {qos}")
                else:
                    print(f"Failed to subscribe to {topic}")  # Added print
                    self.logger.error(f"Failed to subscribe to {topic}")
            except Exception as e:
                print(f"Subscription error for {topic}: {e}")  # Added print
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
        for attempt in range(1, max_retries + 1):
            try:
                if not self.connection_active:
                    print(f"! Not connected to broker - skipping publish to {topic}")
                    return False

                result = self.client.publish(topic, json.dumps(payload), qos=1)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    print(f"✓ Published to {topic} on attempt {attempt}")
                    return True
            except Exception as e:
                print(f"✗ Publish attempt {attempt} failed: {e}")
                time.sleep(self.publish_retry_delay)
                if not self.connection_active:
                    print(f"Reconnection needed before retrying publish to {topic}")
                    self.reconnect_with_fixed_delay()  # Reconnect if needed

        print(f"✗ Failed to publish to {topic} after {max_retries} attempts")
        return False


    def on_message(self, client, userdata, message):
        """Message Handler"""
        try:
            # Skip empty messages (like the ones used to clear retained messages) silently
            if not message.payload or message.payload.decode('utf-8').strip() == "":
                return
            
            print(f"Received message on topic: {message.topic}")

            try:
                # Try parsing the message payload as JSON
                payload = json.loads(message.payload.decode('utf-8'))
                
            except json.JSONDecodeError as e:
                print(f"✗ JSON decode error: {e}")
                self.logger.error(f"JSON decode error for message on {message.topic}: {e}.")
                return  # Skip processing if the message isn't valid JSON
            
            # Direct call to handlers based on topic
            if message.topic in self.handlers:
                self.handlers[message.topic](payload)
            
        except Exception as e:
            print(f"Message processing error: {e}")
            self.logger.error(f"Message processing error: {e}")

    def handle_audio_alert(self, payload):
        """Process Audio Alerts - Non-blocking version"""
        video_alert = {'activate': True}
        result = self.client.publish('video/monitor', json.dumps(video_alert), qos=2)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print("✓ Video activation alert publish initiated (QoS 2 in progress)")
            self.logger.info("Video activation alert sent")
        else:
            print(f"✗ Failed to initiate video activation publish: {result.rc}")
            self.logger.error(f"Failed to initiate video activation publish: {result.rc}")

            # Store variables first 
        phrase = payload.get('phrase', '')
        alert_type = payload.get('alert_type')
        confidence = payload.get('confidence')
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        source = payload.get('source', 'audio')
        
        print(f"Audio Alert: {alert_type}")  # Simple console feedback
        priority = 'HIGH' if alert_type in ['Urgent Assistance', 'Pain/Discomfort'] else 'MEDIUM'
        
        alert_data = {
            'timestamp': timestamp,  # Use current time
            'alert_type': alert_type,
            'confidence': confidence,
            'source': source,
            'details': f"Detected: {phrase}",
            'priority': priority
        }
        
        try:
            # Non-blocking publish (no wait_for_publish)
            result = self.client.publish('nurse/dashboard', json.dumps(alert_data), qos=2)
            
            # Still check initial result code but don't wait for full handshake
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"✓ Audio alert publish initiated (QoS 2 in progress)")
                self.logger.info(f"Audio Alert Started: {phrase}")
            else:
                print(f"✗ Failed to initiate audio alert publish: {result.rc}")

        except Exception as e:
            print(f"✗ Failed to publish audio alert: {e}")
            self.logger.error(f"Failed to publish audio alert: {e}")

    def handle_fall_alert(self, payload):
        """Process Fall Detection Alerts - Non-blocking version"""
        try:
            # Store variables first
            mediapipe_state = payload.get('mediapipe_state')
            #opencv_state = payload.get('opencv_state') #ignored due to not having fallen down
            timestamp = payload.get('timestamp', datetime.now().isoformat())
            source = payload.get('source', 'video')

            print(f"FALL DETECTED: {mediapipe_state}")  # Simple console feedback
            alert_data = {
                    'timestamp': timestamp,  # Use current time
                    'alert_type': 'FALL_DETECTED',
                    'source': source,
                    'details': f"Patient fallen out of bed (MediaPipe: {mediapipe_state})",
                    'priority': 'HIGH'
                }
                
            # Non-blocking publish (no wait_for_publish)
            result = self.client.publish('nurse/dashboard', json.dumps(alert_data), qos=2)
                
                # Still check initial result code but don't wait for full handshake
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"✓ Fall alert publish initiated (QoS 2 in progress)")
                self.logger.info(f"Fall Alert Started")
            else:
                print(f"✗ Failed to initiate fall alert publish: {result.rc}")

        except Exception as e:
            print(f"✗ Failed to publish fall alert: {e}")
            self.logger.error(f"Fall detection error: {e}")

    def handle_proximity_alert(self, payload):
        """Process Proximity Alerts"""
        try:
            print(payload)  # Print the raw payload first
            
            # Extract with correct key names
            out_of_bed = payload.get('out_of_bed', False)
            distances = payload.get('distances', [])  
            timestamp = payload.get('timestamp', datetime.now().isoformat())
            source = payload.get('source', 'proximity')
            
            # Always send proximity data
            proximity_data = {
                'timestamp': timestamp,  # Use CURRENT time for outgoing messages
                'alert_type': 'PROXIMITY_DATA',
                'source': source,
                'distances': distances,
                'priority': 'LOW'
            }
            self.publish_with_retry('nurse/dashboard', proximity_data)
            
            # If patient out of bed
            if out_of_bed:
                # Activate video
                video_alert = {'activate': True}
                self.client.publish('video/monitor', json.dumps(video_alert), qos=2)
                print(f"✓ Video activation alert published")
                
                # Send alert
                alert_data = {
                    'timestamp': timestamp,
                    'alert_type': 'PATIENT_OUT_OF_BED',
                    'source': source,
                    'distances': distances,
                    'priority': 'HIGH'
                }

                result = self.client.publish('nurse/dashboard', json.dumps(alert_data), qos=2)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    print("✓ Out-of-bed alert request sent (QoS 2 in progress)")
                    self.logger.info("Out-of-bed alert request sent")
                else:
                    print(f"✗ Failed to publish out-of-bed alert: {result.rc}")
                    self.logger.error(f"Failed to publish out-of-bed alert: {result.rc}")
            else:
                # Deactivate video
                video_alert = {'activate': False}
                self.client.publish('video/monitor', json.dumps(video_alert), qos=2)
                print(f"✓ Video deactivation published")
        
        except Exception as e:
            print(f"✗ Proximity alert error: {e}")
            self.logger.error(f"Proximity alert error: {e}")

    # def handle_sensor_error(self, payload):
    #     """Handle sensor malfunction alerts"""
    #     try:
    #         error_msg = payload.get('error', 'Unknown sensor error')
    #         timestamp = payload.get('timestamp', datetime.now().isoformat())
            
    #         print(f"SENSOR ERROR: {error_msg}")  # Immediate console feedback
            
    #         # Send high-priority alert to dashboard
    #         alert_data = {
    #             'timestamp': timestamp,
    #             'alert_type': 'SENSOR_MALFUNCTION',
    #             'source': 'proximity',
    #             'details': error_msg,
    #             'priority': 'HIGH'
    #         }
            
    #         result = self.client.publish('nurse/dashboard', json.dumps(alert_data), qos=0)
    #         print(f"✓ Sensor error alert published")
    #         self.logger.error(f"Sensor malfunction reported: {error_msg}")
            
    #         # Activate video monitoring as backup
    #         video_alert = {'activate': True}
    #         result = self.client.publish('video/monitor', json.dumps(video_alert), qos=2)
    #         result.wait_for_publish()
    #         if result.is_published():
    #             print(f"✓ Video activation (due to sensor error) published")
            
    #     except Exception as e:
    #         print(f"✗ Error handling sensor malfunction: {e}")
    #         self.logger.error(f"Failed to process sensor error: {e}")

    def start(self):
        """Start the Central Hub"""
        try:
            # Add callbacks BEFORE connecting
            self.client.on_connect = self.on_connect
            self.client.on_message = self.on_message
            self.client.on_disconnect = self.on_disconnect
            
            # Enable MQTT keepalive
            self.client.keepalive = 120
            
            print("Starting Central Hub...")
            print("Waiting for messages...")
            
            # Connect and start loop
            self.client.connect(self.broker_address, self.broker_port, 60)
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
        hub.client.disconnect()  # Graceful disconnect
        hub.client.loop_stop()   # Stop the loop after disconnect
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        hub.client.disconnect()  # Ensure disconnect even on exceptions
        hub.client.loop_stop()   # Stop the loop in case of errors


if __name__ == "__main__":
    main()

