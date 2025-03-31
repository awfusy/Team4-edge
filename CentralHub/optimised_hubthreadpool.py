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
from concurrent.futures import ThreadPoolExecutor

class OptimizedCentralHub:
    def __init__(self, broker_address='192.168.61.254', broker_port=1883, reconnect_delay=2, publish_retry_delay=1):
        self.client_id = "CentralHub"
        self.client = mqtt.Client(client_id=self.client_id, clean_session=False)
        
        self.broker_address = broker_address
        self.broker_port = broker_port
        self.reconnect_delay = reconnect_delay
        self.publish_retry_delay = publish_retry_delay
        self._last_camera_state = None 
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
        
        # Fixed queue sizes (can also be made dynamic if needed)
        self.message_queue = queue.Queue(maxsize=100)
        self.proximity_publish_queue = queue.Queue(maxsize=100)
        self.qos2_publish_queue = queue.Queue(maxsize=100)

        self.logger.info(f"Queue sizes - Message: {self.message_queue.maxsize}, "
                        f"Proximity: {self.proximity_publish_queue.maxsize}, "
                        f"QoS 2: {self.qos2_publish_queue.maxsize}")

        self.running = False
        self.executor_message = None
        self.executor_proximity = None
        self.executor_qos2 = None
        self.heartbeat_thread = None

        # Dynamic thread pool settings
        self.base_thread_count = max(1, os.cpu_count() // 2)  # Start with half the CPU cores
        self.max_thread_count = max(4, os.cpu_count())  # Cap at CPU core count or a minimum of 4
        self.thread_scaling_interval = 10  # Check scaling every 10 seconds

    def adjust_thread_pool(self):
        """Dynamically adjust the number of threads based on queue sizes and system resources."""
        def calculate_thread_count(queue_size, max_queue_size, base_count, max_count):
            load_factor = queue_size / max_queue_size  # How full is the queue?
            available_memory = psutil.virtual_memory().available / (1024 * 1024)  # MB
            if available_memory < 100:  # Low memory threshold
                return base_count  # Scale down to base if memory is low
            return min(max_count, max(base_count, int(base_count + (load_factor * max_count))))

        # Adjust message processor threads
        message_threads = calculate_thread_count(
            self.message_queue.qsize(), self.message_queue.maxsize, self.base_thread_count, self.max_thread_count
        )
        if self.executor_message._max_workers != message_threads:
            self.executor_message._max_workers = message_threads
            self.logger.info(f"Adjusted message threads to {message_threads}")

        # Adjust proximity publisher threads
        proximity_threads = calculate_thread_count(
            self.proximity_publish_queue.qsize(), self.proximity_publish_queue.maxsize, self.base_thread_count, self.max_thread_count
        )
        if self.executor_proximity._max_workers != proximity_threads:
            self.executor_proximity._max_workers = proximity_threads
            self.logger.info(f"Adjusted proximity threads to {proximity_threads}")

        # Adjust QoS 2 publisher threads
        qos2_threads = calculate_thread_count(
            self.qos2_publish_queue.qsize(), self.qos2_publish_queue.maxsize, self.base_thread_count, self.max_thread_count
        )
        if self.executor_qos2._max_workers != qos2_threads:
            self.executor_qos2._max_workers = qos2_threads
            self.logger.info(f"Adjusted QoS 2 threads to {qos2_threads}")


    def thread_pool_monitor(self):
        """Periodically monitor and adjust thread pools based on system load."""
        while self.running:
            try:
                cpu_usage = psutil.cpu_percent(interval=1)  # Monitor CPU usage
                memory_usage = psutil.virtual_memory().percent  # Monitor memory usage

                # Determine appropriate interval based on resource usage
                if cpu_usage > 80 or memory_usage > 80:  # High resource usage
                    self.adjust_thread_pool()  # Adjust the thread pool
                    time.sleep(5)  # Check more frequently under high load
                elif cpu_usage > 50 or memory_usage > 50:  # Moderate resource usage
                    self.adjust_thread_pool()  # Adjust the thread pool
                    time.sleep(10)  # Moderate check interval
                else:
                    time.sleep(20)  # Check less frequently under idle conditions
            except Exception as e:
                self.logger.error(f"Thread pool monitor error: {e}")
                time.sleep(10)  # Sleep for a default interval if there's an error


    # MQTT callbacks (on_connect, on_disconnect, etc.) remain the same
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
        aggressive_attempts = 4
        aggressive_delay = 1
        while not self.connection_active and self.running and attempt <= max_attempts:
            try:
                self.logger.info(f"Reconnection attempt {attempt}")
                self.client.reconnect()
                break
            except Exception as e:
                self.logger.error(f"Reconnection attempt {attempt} failed: {e}")
                if attempt < aggressive_attempts:
                    delay = aggressive_delay
                else:
                    exp_attempt = attempt - aggressive_attempts
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

    def proximity_publisher_worker(self, topic, payload, max_retries):
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

    def qos2_publisher_worker(self, topic, payload):
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

    def heartbeat(self):
        while self.running:
            try:
                if self.connection_active:
                    available_memory_mb = psutil.virtual_memory().available / (1024 * 1024)  # Available memory in MB
                    total_memory_mb = psutil.virtual_memory().total / (1024 * 1024)  # Total memory in MB
                    disk_usage = psutil.disk_usage('/').percent  # Disk usage percentage
                    load_avg = os.getloadavg()  # System load averages for 1, 5, and 15 minutes
                    network_io = psutil.net_io_counters()  # Network I/O stats
                    swap_memory = psutil.swap_memory()  # Swap memory usage

                    heartbeat_msg = {
                        'timestamp': datetime.now().isoformat(),
                        'status': 'alive',
                        'cpu': psutil.cpu_percent(),
                        'memory': psutil.virtual_memory().percent,
                        'available_memory': available_memory_mb,
                        'total_memory': total_memory_mb,
                        'disk_usage': disk_usage,
                        'load_average': load_avg,
                        'network_in': network_io.bytes_recv,  # Total received bytes
                        'network_out': network_io.bytes_sent,  # Total sent bytes
                        'swap_used': swap_memory.percent  # Swap memory usage
                    }

                    self.client.publish_with_retry('hub/heartbeat', json.dumps(heartbeat_msg), qos=1)
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

    def message_processor(self, message):
        start_time = time.time()
        print(f"Processing {message.topic}")
        try:
            if not message.payload:
                self.message_queue.task_done()
                return
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
            if self.message_queue.qsize() >= 0.8 * self.message_queue.maxsize:
                gc.collect()

    def handle_audio_alert(self, payload):
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        source = payload.get('source', 'audio')

        video_alert = {'activate': True,
                       'timestamp': timestamp,  
                       'source': source}
        dashboard_camera_activation_alert = {'activate': True,
                       'timestamp': timestamp,  
                       'source': 'camera_activation'}               
        self.publish_qos2('video/monitor', video_alert)
        self.publish_qos2('nurse/dashboard', dashboard_camera_activation_alert)
        phrase = payload.get('phrase', '')
        alert_type = payload.get('alert_type')
        confidence = payload.get('confidence')
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
        mediapipe_state = payload.get('mediapipe_state','No fall detected (Standing, Sitting, Lying Down)')
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        source = payload.get('source', 'video')
        camera_state = payload.get('cameraState', False)  # True for activated, False for deactivated
        print(f"Patient state: {mediapipe_state}")
        priority = 'HIGH' if mediapipe_state == 'Fallen out of bed' else 'MEDIUM'
        # Creating alert data for fall detection
        alert_data = {
            'timestamp': timestamp,
            'alert_type': 'FALL_DETECTED',
            'source': source,
            'details': mediapipe_state,
            'priority': priority
        }
        
        # Publish fall detection alert
        self.publish_qos2('nurse/dashboard', alert_data)
        
        # Only send camera state change if it's different from the last state
        if camera_state != self._last_camera_state:
            # Update the tracked state
            self._last_camera_state = camera_state
            
            # Send camera activation/deactivation message
            dashboard_camera_state_alert = {
                'timestamp': timestamp,
                'source': 'camera_activation',
                'activate': camera_state
            }
            self.publish_qos2('nurse/dashboard', dashboard_camera_state_alert)
            print(f"Camera {'activated' if camera_state else 'deactivated'} at {timestamp}")
            self.logger.info(f"Camera state changed to {'activated' if camera_state else 'deactivated'}")
        else:
            print(f"Camera state unchanged ({camera_state}), not sending update")
            self.logger.debug(f"Camera state unchanged ({camera_state}), not sending update")

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
                'details': details,
                'distances': distances,
                'priority': 'LOW'
            }
            self.publish_with_retry('nurse/dashboard', proximity_data)
             # Always send patient out-of-bed alert if applicable
            if out_of_bed:
                alert_data = {
                    'timestamp': timestamp,
                    'alert_type': 'PATIENT_OUT_OF_BED',
                    'source': source,
                    'distances': distances,
                    'priority': 'HIGH'
                }
                self.publish_qos2('nurse/dashboard', alert_data)
                self.logger.info("Out-of-bed alert sent")

            # Determine the desired camera state based on out_of_bed status
            camera_state = out_of_bed  # True if out of bed, False otherwise
            
            # Only send camera state change if it's different from the last state
            if camera_state != self._last_camera_state:
                # Update the tracked state
                self._last_camera_state = camera_state
                
                # Common message for both video/monitor and nurse/dashboard
                camera_state_msg = {
                    'timestamp': timestamp,
                    'source': source,
                    'activate': camera_state
                }
                
                # Send to video/monitor
                self.publish_qos2('video/monitor', camera_state_msg)
                
                # Send to nurse/dashboard
                dashboard_camera_state_alert = {
                    'timestamp': timestamp,
                    'source': 'camera_activation',
                    'activate': camera_state
                }
                self.publish_qos2('nurse/dashboard', dashboard_camera_state_alert)
                
                print(f"Camera {'activated' if camera_state else 'deactivated'} at {timestamp}")
                self.logger.info(f"Camera state changed to {'activated' if camera_state else 'deactivated'}")
            else:
                print(f"Camera state unchanged ({camera_state}), not sending update")
                self.logger.debug(f"Camera state unchanged ({camera_state}), not sending update")
            
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
            
            print("Starting Central Hub...")
            
            # Initialize thread pools
            self.executor_message = ThreadPoolExecutor(max_workers=self.base_thread_count)
            self.executor_proximity = ThreadPoolExecutor(max_workers=self.base_thread_count)
            self.executor_qos2 = ThreadPoolExecutor(max_workers=self.base_thread_count)
            self.heartbeat_thread = threading.Thread(target=self.heartbeat, daemon=True)
            self.thread_pool_monitor_thread = threading.Thread(target=self.thread_pool_monitor, daemon=True)

            # Start heartbeat and thread pool monitor
            self.heartbeat_thread.start()
            self.thread_pool_monitor_thread.start()

            # Submit tasks to thread pools
            def submit_tasks():
                while self.running:
                    try:
                        # Message processing
                        message = self.message_queue.get(block=True, timeout=1)
                        self.executor_message.submit(self.message_processor, message)
                    except queue.Empty:
                        pass
                    try:
                        # Proximity publishing
                        topic, payload, max_retries = self.proximity_publish_queue.get(block=True, timeout=1)
                        self.executor_proximity.submit(self.proximity_publisher_worker, topic, payload, max_retries)
                    except queue.Empty:
                        pass
                    try:
                        # QoS 2 publishing
                        topic, payload = self.qos2_publish_queue.get(block=True, timeout=1)
                        self.executor_qos2.submit(self.qos2_publisher_worker, topic, payload)
                    except queue.Empty:
                        pass

            threading.Thread(target=submit_tasks, daemon=True).start()
            
            print("Thread pools started")
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
        
        # Shutdown thread pools
        if self.executor_message:
            self.executor_message.shutdown(wait=True)
        if self.executor_proximity:
            self.executor_proximity.shutdown(wait=True)
        if self.executor_qos2:
            self.executor_qos2.shutdown(wait=True)
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=2)
        if self.thread_pool_monitor_thread and self.thread_pool_monitor_thread.is_alive():
            self.thread_pool_monitor_thread.join(timeout=2)
        
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
