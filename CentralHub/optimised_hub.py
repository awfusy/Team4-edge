import paho.mqtt.client as mqtt
import json
import logging
import logging.handlers
from datetime import datetime
import time
import threading
import queue
import gc
import psutil
import os

class OptimizedCentralHub:
    def __init__(self, broker_address='192.168.61.254', broker_port=1883, reconnect_delay=2, publish_retry_delay=1):
        self.client_id = "CentralHub"
        self.client = mqtt.Client(client_id=self.client_id, clean_session=False)
        
        self.broker_address = broker_address
        self.broker_port = broker_port
        self.reconnect_delay = reconnect_delay
        self.publish_retry_delay = publish_retry_delay
        
        # Logging with timed rotation
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s: %(message)s',
           handlers=[
                logging.handlers.RotatingFileHandler(
                    'Optimised_central_hub.log', 
                    maxBytes=100*1024*1024,  # 100MB file size
                    backupCount=3        # Keep 3 backup files
                ),
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        self.topics = {
            'audio/emergency': 2,
            'video/emergency': 2,
            'proximity/alert': 2,
        }
        
        self.handlers = {
            'proximity/alert': self.handle_proximity_alert,
            'audio/emergency': self.handle_audio_alert,
            'video/emergency': self.handle_fall_alert
        }

        self.connection_active = False
        
        # available_memory_mb = psutil.virtual_memory().available / (1024 * 1024)  # MB
        # self.message_queue = queue.Queue(maxsize=min(200, int(available_memory_mb / 4)))  # Max 200
        # self.proximity_publish_queue = queue.Queue(maxsize=min(100, int(available_memory_mb / 6)))  # Max 100
        # self.qos2_publish_queue = queue.Queue(maxsize=min(200, int(available_memory_mb / 4)))  # Max 200
        # self.logger.info(f"Queue sizes - Message: {self.message_queue.maxsize}, "
        #                 f"Proximity: {self.proximity_publish_queue.maxsize}, "
        #                 f"QoS 2: {self.qos2_publish_queue.maxsize}")

        # # Set fixed queue sizes
        self.message_queue = queue.Queue(maxsize=100)  # Fixed size of 100
        self.proximity_publish_queue = queue.Queue(maxsize=100)  # Fixed size of 100
        self.qos2_publish_queue = queue.Queue(maxsize=100)  # Fixed size of 100

        # Log the queue sizes
        self.logger.info(f"Queue sizes - Message: {self.message_queue.maxsize}, "
                        f"Proximity: {self.proximity_publish_queue.maxsize}, "
                        f"QoS 2: {self.qos2_publish_queue.maxsize}")

        
        self.running = False
        self.worker_thread = None
        self.publisher_thread = None
        self.qos2_publisher_thread = None
        self.heartbeat_thread = None

    # def recover_qos2_fallback(self):
    #     """Re-queue QoS 2 messages from fallback log on startup"""
    #     fallback_file = "qos2_fallback.log"
    #     if not os.path.exists(fallback_file):
    #         return
        
    #     with open(fallback_file, "r") as f:
    #         lines = f.readlines()
        
    #     for line in lines:
    #         try:
    #             timestamp, topic_payload = line.strip().split(" - ", 1)
    #             topic, payload = topic_payload.split(": ", 1)
    #             payload = json.loads(payload)
    #             if self.qos2_publish_queue.qsize() < self.qos2_publish_queue.maxsize:
    #                 self.qos2_publish_queue.put((topic, payload), block=False)
    #                 self.logger.info(f"Recovered QoS 2 message from {topic}")
    #             else:
    #                 self.logger.warning(f"QoS 2 queue full - cannot recover {topic}")
    #         except Exception as e:
    #             self.logger.error(f"Failed to recover QoS 2 message: {e}")
        
    #     # Clear the file after recovery
    #     with open(fallback_file, "w") as f:
    #         f.write("")

    def on_connect(self, client, userdata, flags, rc):
        connection_codes = {
            0: "Connected successfully",
            1: "Incorrect protocol version",
            2: "Invalid client identifier",
            3: "Server unavailable",
            4: "Bad username or password",
            5: "Not authorized"
        }
        
        if rc != 0:
            print(f"Connection failed: {connection_codes.get(rc, 'Unknown error')}")
            self.connection_active = False
            self.logger.error(f"Connection failed: {connection_codes.get(rc, 'Unknown error')}")
            return

        print(f"Connected to MQTT Broker: {self.broker_address}")
        self.connection_active = True
        self.logger.info(f"Connected to broker {self.broker_address}")
        
        for topic in self.topics:
            self.client.publish(topic, "", qos=1, retain=True)
        
        subscription_list = [(topic, qos) for topic, qos in self.topics.items()]
        result, mid = self.client.subscribe(subscription_list)
        
        if result == mqtt.MQTT_ERR_SUCCESS:
            topic_list_str = ", ".join(f"{topic} (QoS: {qos})" for topic, qos in self.topics.items())
            print(f"Subscribed to {len(subscription_list)} topics: {topic_list_str}")
            self.logger.info(f"Subscribed to topics: {', '.join(self.topics.keys())}")
        else:
            print(f"Failed to subscribe: {result}")
            self.logger.error(f"Failed to subscribe: {result}")

    def on_disconnect(self, client, userdata, rc):
        disconnect_time = datetime.now().isoformat()
        self.connection_active = False
        
        if rc != 0:
            print(f"Unexpected disconnection at {disconnect_time}")
            self.logger.warning(f"Unexpected disconnection at {disconnect_time}. Reconnecting...")
            threading.Thread(target=self.reconnect_with_fixed_delay, daemon=True).start()

    def reconnect_with_fixed_delay(self):
        attempt = 1
        max_attempts = 10
        max_delay = 60
        aggressive_attempts = 4  # First 4 attempts are aggressive
        aggressive_delay = 1   # 1 seconds for aggressive phase
        
        while not self.connection_active and self.running and attempt <= max_attempts:
            try:
                self.logger.info(f"Reconnection attempt {attempt}")
                self.client.reconnect()
                break
            except Exception as e:
                self.logger.error(f"Reconnection attempt {attempt} failed: {e}")
                if attempt < aggressive_attempts:
                    # Aggressive phase: fixed short delay
                    delay = aggressive_delay
                else:
                    # Exponential phase: backoff starts after aggressive attempts
                    exp_attempt = attempt - aggressive_attempts  # Adjust for exponential indexing
                    delay = min(self.reconnect_delay * (2 ** exp_attempt), max_delay)
                attempt += 1
                time.sleep(delay)
        if attempt > max_attempts:
            self.logger.critical("Max reconnection attempts reached")

    def publish_with_retry(self, topic, payload, max_retries=3):
        if not self.connection_active:
            print(f"! Not connected - queuing QoS 1 to {topic}")
        try:
            self.proximity_publish_queue.put((topic, payload, max_retries), block=False)
            return True
        except queue.Full:
            print(f"✗ QoS 1 queue full - discarding {topic}")
            self.logger.error(f"QoS 1 queue full - discarded {topic}")
            return False

    def publish_qos2(self, topic, payload):
        if not self.connection_active:
            print(f"! Not connected - cannot queue QoS 2 to {topic}")
            return False
        if self.qos2_publish_queue.qsize() >= 0.8 * self.qos2_publish_queue.maxsize:
            self.logger.warning(f"QoS 2 queue at {self.qos2_publish_queue.qsize()}/{self.qos2_publish_queue.maxsize}")
            with open("qos2_fallback.log", "a") as f:
                f.write(f"{datetime.now().isoformat()} - {topic}: {json.dumps(payload)}\n")
        try:
            self.qos2_publish_queue.put((topic, payload), block=False)
            return True
        except queue.Full:
            self.logger.critical(f"QoS 2 queue full - persisting {topic}")
            with open("qos2_fallback.log", "a") as f:
                f.write(f"{datetime.now().isoformat()} - {topic}: {json.dumps(payload)}\n")
            return False

    def proximity_publisher_worker(self):
        while self.running:
            try:
                topic, payload, max_retries = self.proximity_publish_queue.get(block=True, timeout=1)
                success = False
                for attempt in range(1, max_retries + 1):
                    try:
                        if not self.connection_active:
                            time.sleep(self.publish_retry_delay)
                            continue
                        result = self.client.publish(topic, json.dumps(payload), qos=1)
                        if result.rc == mqtt.MQTT_ERR_SUCCESS:
                            print(f"✓ QoS 1 to {topic} on attempt {attempt}")
                            success = True
                            break
                    except Exception as e:
                        print(f"✗ QoS 1 attempt {attempt}: {e}")
                        time.sleep(self.publish_retry_delay)
                if not success:
                    self.logger.error(f"QoS 1 failed to {topic} after {max_retries}")
                self.proximity_publish_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"QoS 1 publisher error: {e}")
                time.sleep(1)

    def qos2_publisher_worker(self):
        while self.running:
            try:
                topic, payload = self.qos2_publish_queue.get(block=True, timeout=1)
                for attempt in range(1, 4):
                    try:
                        if not self.connection_active:
                            time.sleep(1)
                            continue
                        start_time = time.time()
                        result = self.client.publish(topic, json.dumps(payload), qos=2)
                        latency = (time.time() - start_time) * 1000  # ms
                        if result.rc == mqtt.MQTT_ERR_SUCCESS:
                            print(f"✓ QoS 2 to {topic} on attempt {attempt} ({latency:.2f}ms)")
                            self.logger.info(f"QoS 2 to {topic} ({latency:.2f}ms)")
                            break
                        print(f"✗ QoS 2 attempt {attempt}: {result.rc}")
                        self.logger.error(f"QoS 2 attempt {attempt}: {result.rc}")
                        time.sleep(1)
                    except Exception as e:
                        print(f"✗ QoS 2 attempt {attempt}: {e}")
                        self.logger.error(f"QoS 2 attempt {attempt}: {e}")
                        time.sleep(1)
                else:
                    self.logger.critical(f"QoS 2 to {topic} failed after 3 retries")
                self.qos2_publish_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"QoS 2 worker error: {e}")
                time.sleep(1)

    def heartbeat(self):
        """Publish a heartbeat every 30 seconds to monitor system health"""
        while self.running:
            try:
                if self.connection_active:
                    # Dynamic queue sizes based on available memory
                    available_memory_mb = psutil.virtual_memory().available / (1024 * 1024)  # MB
                    heartbeat_msg = {
                        'timestamp': datetime.now().isoformat(),
                        'status': 'alive',
                        'cpu': psutil.cpu_percent(),
                        'memory': psutil.virtual_memory().percent,
                        'available_memory': available_memory_mb
                    }
                    self.client.publish('hub/heartbeat', json.dumps(heartbeat_msg), qos=1)
                    self.logger.debug("Heartbeat sent")
                time.sleep(30)
            except Exception as e:
                self.logger.error(f"Heartbeat error: {e}")
                time.sleep(30)

    def on_message(self, client, userdata, message):
        try:
            if not message.payload or message.payload.decode('utf-8').strip() == "":
                return
            if self.message_queue.qsize() >= 0.8 * self.message_queue.maxsize:
                self.logger.warning(f"Message queue at {self.message_queue.qsize()}/{self.message_queue.maxsize}")
            try:
                self.message_queue.put(message, block=False)
            except queue.Full:
                self.logger.error(f"Message queue full - dropping {message.topic}")
        except Exception as e:
            print(f"Message queueing error: {e}")
            self.logger.error(f"Message queueing error: {e}")

    def message_processor(self):
        message_count = 0
        while self.running:
            try:
                message = self.message_queue.get(block=True, timeout=1)
                start_time = time.time()
                print(f"Processing {message.topic}")
                try:
                    if not message.payload:
                        self.message_queue.task_done()
                        continue
                    payload = json.loads(message.payload.decode('utf-8'))
                    if message.topic in self.handlers:
                        self.handlers[message.topic](payload)
                except json.JSONDecodeError as e:
                    print(f"✗ JSON decode error: {e}")
                    self.logger.error(f"JSON decode error on {message.topic}: {e}")
                except Exception as e:
                    print(f"Message handling error: {e}")
                    self.logger.error(f"Message handling error on {message.topic}: {e}")
                finally:
                    latency = (time.time() - start_time) * 1000  # ms
                    self.message_queue.task_done()
                    message_count += 1
                    if message_count % 50 == 0:
                        self.logger.info(f"Processed {message_count} messages, "
                                       f"CPU: {psutil.cpu_percent()}%, "
                                       f"Memory: {psutil.virtual_memory().percent}%, "
                                       f"Last latency: {latency:.2f}ms")
                    if self.message_queue.qsize() >= 0.8 * self.message_queue.maxsize:
                        gc.collect()
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Message processor error: {e}")
                time.sleep(1)

    def handle_audio_alert(self, payload):
        video_alert = {'activate': True}
        self.publish_qos2('video/monitor', video_alert)
        
        phrase = payload.get('phrase', '')
        alert_type = payload.get('alert_type')
        confidence = payload.get('confidence')
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        source = payload.get('source', 'audio')
        
        print(f"Audio Alert: {alert_type}")
        priority = 'HIGH' if alert_type in ['Urgent Assistance', 'Pain/Discomfort'] else 'MEDIUM'
        
        alert_data = {
            'timestamp': timestamp,
            'alert_type': alert_type,
            'confidence': confidence,
            'source': source,
            'details': f"Detected: {phrase}",
            'priority': priority
        }
        self.publish_qos2('nurse/dashboard', alert_data)
        self.logger.info(f"Audio Alert: {phrase}")

    def handle_fall_alert(self, payload):
        mediapipe_state = payload.get('mediapipe_state')
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        source = payload.get('source', 'video')

        print(f"FALL DETECTED: {mediapipe_state}")
        alert_data = {
            'timestamp': timestamp,
            'alert_type': 'FALL_DETECTED',
            'source': source,
            'details': mediapipe_state,
            'priority': 'HIGH'
        }
        self.publish_qos2('nurse/dashboard', alert_data)
        self.logger.info("Fall Alert Sent")

    def handle_proximity_alert(self, payload):
        try:
            out_of_bed = payload.get('out_of_bed', False)
            distances = payload.get('distances', [])  
            timestamp = payload.get('timestamp', datetime.now().isoformat())
            source = payload.get('source', 'proximity')
            details = 'Out of bed' if out_of_bed else 'Still in bed'
            proximity_data = {
                'timestamp': timestamp,
                'alert_type': 'PROXIMITY_DATA',
                'source': source,
                'distances': distances,
                'details': details,
                'priority': 'LOW'
            }
            self.publish_with_retry('nurse/dashboard', proximity_data)
            
            if out_of_bed:
                video_alert = {'activate': True}
                self.publish_qos2('video/monitor', video_alert)
                alert_data = {
                    'timestamp': timestamp,
                    'alert_type': 'PATIENT_OUT_OF_BED',
                    'source': source,
                    'distances': distances,
                    'priority': 'HIGH'
                }
                self.publish_qos2('nurse/dashboard', alert_data)
                self.logger.info("Out-of-bed alert sent")
        except Exception as e:
            print(f"✗ Proximity alert error: {e}")
            self.logger.error(f"Proximity alert error: {e}")

    def start(self):
        try:
            self.running = True
            self.client.on_connect = self.on_connect
            self.client.on_message = self.on_message
            self.client.on_disconnect = self.on_disconnect
            self.client.keepalive = 120
            
            #self.client.recover_qos2_fallback()
            
            print("Starting Central Hub...")
            
            self.worker_thread = threading.Thread(target=self.message_processor, daemon=True)
            self.worker_thread.start()
            self.publisher_thread = threading.Thread(target=self.proximity_publisher_worker, daemon=True)
            self.publisher_thread.start()
            self.qos2_publisher_thread = threading.Thread(target=self.qos2_publisher_worker, daemon=True)
            self.qos2_publisher_thread.start()
            self.heartbeat_thread = threading.Thread(target=self.heartbeat, daemon=True)
            self.heartbeat_thread.start()
            
            print("Worker threads started")
            print("Waiting for messages...")
            
            self.client.connect(self.broker_address, self.broker_port, 60)
            self.client.loop_forever()
        except Exception as e:
            self.logger.error(f"Startup error: {e}")
            self.running = False
            raise

    def stop(self):
        self.running = False
        
        for q in [self.message_queue, self.proximity_publish_queue, self.qos2_publish_queue]:
            while not q.empty():
                try:
                    q.get_nowait()
                    q.task_done()
                except queue.Empty:
                    break
        
        for thread in [self.worker_thread, self.publisher_thread, self.qos2_publisher_thread, self.heartbeat_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=2)
        
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
        self.logger.info("Central Hub stopped cleanly")

def main():
    hub = OptimizedCentralHub()
    try:
        hub.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        logging.info("Shutting down via interrupt...")
        hub.stop()
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        hub.stop()

if __name__ == "__main__":
    main()