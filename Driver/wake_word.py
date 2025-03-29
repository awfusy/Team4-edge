import tflite_runtime.interpreter as tflite
import sounddevice as sd
import numpy as np
import librosa
import queue
import time
import warnings
import subprocess
import noisereduce as nr
from vosk import Model, KaldiRecognizer
import json
import threading
import os
import paho.mqtt.client as mqtt
from datetime import datetime

warnings.filterwarnings("ignore", category=UserWarning)
# Add MQTT Configuration
MQTT_BROKER = "192.168.18.138"
MQTT_PORT = 1883
MQTT_TOPIC = "audio/emergency"

# Initialize MQTT client
client = mqtt.Client()

# Add MQTT callbacks
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

# Add callbacks to client
client.on_connect = on_connect
client.on_disconnect = on_disconnect

# Modify the MQTT connection part
try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
except Exception as e:
    print(f"Failed to connect to MQTT broker: {e}")
    # Don't exit, let it try to reconnect

def send_mqtt_alert(class_id, confidence, detected_phrase=""):
    """Send alert to MQTT broker"""
    alert_data = {
        "timestamp": datetime.now().isoformat(),
        "alert_type": CLASS_LABELS[class_id],
        "confidence": float(confidence),
        "phrase": detected_phrase,
        "source": "audio"
    }
    try:
        # Store result of publish
        result = client.publish(MQTT_TOPIC, json.dumps(alert_data), qos=2)
        
        # Wait for publish to complete (for QoS 2)
        result.wait_for_publish()
        
        if result.is_published():
            print(f"✓ MQTT Alert successfully published")
            print(f"  Details: {alert_data}")
        else:
            print(f"! MQTT Alert may not have been delivered")
            
    except Exception as e:
        print(f"✗ Failed to send MQTT message: {e}")


# --- Configuration ---
SAMPLE_RATE = 16000
DURATION = 1.0  # 1-second audio chunks
CHUNK_SIZE = int(SAMPLE_RATE * DURATION)
TFLITE_MODEL_PATH = "../ML/model_quant.tflite"  # Mel spectrogram-based TFLite model
VOSK_MODEL_PATH = "../ML/vosk-model-small-en-us-0.15"
INPUT_SHAPE = (128, 100)  # Mel spectrogram shape from your first script
THRESHOLD = 0.5
COOLDOWN_SECONDS = 10
KEYWORDS = [
    "help", "emergency", "nurse", "doctor", "pain", "medicine",
    "assist", "urgent", "sick", "fall", "bleeding", "call", "please"
]

CLASS_LABELS = {
    0: "General Help",
    1: "Call for Medical Staff",
    2: "Pain/Discomfort",
    3: "Urgent Assistance",
}

# --- Load TFLite Model ---
interpreter = tflite.Interpreter(model_path=TFLITE_MODEL_PATH)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

# --- Load Vosk Model ---
if not os.path.exists(VOSK_MODEL_PATH):
    print(f"Vosk model path {VOSK_MODEL_PATH} does not exist. Exiting.")
    exit(1)
vosk_model = Model(VOSK_MODEL_PATH)
recognizer = KaldiRecognizer(vosk_model, SAMPLE_RATE)

# --- Audio Device Selection ---
def find_input_device(target_keywords=["USB Audio", "USB", "Mic"]):
    devices = sd.query_devices()
    for i, device in enumerate(devices):
        if device['max_input_channels'] > 0:
            if any(keyword.lower() in device['name'].lower() for keyword in target_keywords):
                print(f"Found matching mic: {device['name']} (index {i})")
                return i
    print("No matching USB mic found, using default.")
    return sd.default.device[0]

AUDIO_DEVICE = find_input_device()

# --- Audio Queue ---
audio_queue = queue.Queue()

# --- Feature Extraction for TFLite (Mel Spectrograms) ---
mel_filter = librosa.filters.mel(sr=SAMPLE_RATE, n_fft=1024, n_mels=128)

def extract_mel_spectrogram(audio):
    audio = librosa.effects.preemphasis(audio, coef=0.97)
    stft = librosa.stft(audio, n_fft=1024, hop_length=160)
    spectrogram = np.abs(stft) ** 2
    mel = np.dot(mel_filter, spectrogram)
    log_mel = librosa.power_to_db(mel, ref=np.max)
    if log_mel.shape[1] > INPUT_SHAPE[1]:
        log_mel = log_mel[:, :INPUT_SHAPE[1]]
    else:
        log_mel = np.pad(log_mel, ((0, 0), (0, max(0, INPUT_SHAPE[1] - log_mel.shape[1]))))
    return log_mel.reshape(1, *INPUT_SHAPE, 1).astype(np.float32)

# --- TFLite Inference ---
def tflite_predict(features):
    interpreter.set_tensor(input_details[0]['index'], features)
    interpreter.invoke()
    return interpreter.get_tensor(output_details[0]['index'])

# --- Audio Processing Thread ---
def audio_processing_thread():
    last_trigger_time = 0
    fall_process = None
    while True:
        try:
            audio = audio_queue.get()
            start_time = time.time()

            # Skip low-energy frames
            if np.sqrt(np.mean(audio ** 2)) < 0.005:
                print("Skipping low energy frame (silence)")
                continue

            # Noise reduction
            audio_cleaned = nr.reduce_noise(y=audio.flatten(), sr=SAMPLE_RATE)

            # TFLite Detection (Mel Spectrograms)
            features = extract_mel_spectrogram(audio_cleaned)
            current_time = time.time()



            predictions = tflite_predict(features)
            tflite_detected = False
            # Check if previous process has ended
            if fall_process is not None and fall_process.poll() is not None:
                # Process ended
                print("Fall detection process has finished.")
                fall_process = None  # Reset tracker

            # --- TFLite Detection ---
            for i, score in enumerate(predictions[0]):
                if i != 4 and score >= THRESHOLD:
                    if current_time - last_trigger_time > COOLDOWN_SECONDS and fall_process is None:
                        class_label = CLASS_LABELS.get(i, f"Class {i}")
                        print(f"TFLite Detected! Class: {class_label} (Confidence: {score:.2f})")
                        send_mqtt_alert(i, score)
                        #fall_process = subprocess.Popen(["python3", "falldetection4.py"])
                        last_trigger_time = current_time
                    tflite_detected = True
                    break

            # --- Vosk Fallback ---
            if not tflite_detected and current_time - last_trigger_time > COOLDOWN_SECONDS and fall_process is None:
                if recognizer.AcceptWaveform(audio_cleaned.tobytes()):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").lower()
                    if text and any(keyword in text for keyword in KEYWORDS):
                        print(f"Vosk Detected: {text}")
                        send_mqtt_alert(3, 0.75, text)
                        #fall_process = subprocess.Popen(["python3", "falldetection4.py"])
                        last_trigger_time = current_time

            # Processing time
            print(f"Processing time: {1000 * (time.time() - start_time):.1f}ms")
            audio_queue.task_done()

        except Exception as e:
            print(f"Error: {e}")

# --- Audio Callback ---
def audio_callback(indata, frames, time, status):
    audio_queue.put(indata.copy().flatten())

# --- Main Function ---
def main():
    print("Starting combined wake word detector (no YAMNet)...")
    threading.Thread(target=audio_processing_thread, daemon=True).start()

    with sd.InputStream(samplerate=SAMPLE_RATE,
                        channels=1,
                        device=AUDIO_DEVICE,
                        blocksize=CHUNK_SIZE,
                        callback=audio_callback):
        print("Listening... (Press Ctrl+C to stop)")
        try:
            while True:
                time.sleep(0.1)  # Keep main thread alive
        except KeyboardInterrupt:
            print("Stopping...")

if __name__ == "__main__":
    main()
