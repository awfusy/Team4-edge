import tflite_runtime.interpreter as tflite
import sounddevice as sd
import numpy as np
import librosa
import queue
import time
import warnings
import noisereduce as nr
from vosk import Model, KaldiRecognizer
import json
import threading
import os
import paho.mqtt.client as mqtt
from datetime import datetime

warnings.filterwarnings("ignore", category=UserWarning)

# MQTT Configuration
MQTT_BROKER = "192.168.61.254"
MQTT_PORT = 1883
MQTT_TOPIC = "audio/emergency"
MQTT_BUFFER_SECONDS = 30  # Buffer time between MQTT messages

# Initialize MQTT client
client = mqtt.Client()
last_mqtt_time = 0  # Track last MQTT send time globally


# MQTT Callbacks
def on_connect(client, userdata, flags, rc):
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
    if rc != 0:
        print(f"Unexpected disconnection. Code: {rc}")
        try:
            client.reconnect()
        except Exception as e:
            print(f"Reconnection failed: {e}")


client.on_connect = on_connect
client.on_disconnect = on_disconnect

try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
except Exception as e:
    print(f"Failed to connect to MQTT broker: {e}")


def send_mqtt_alert(class_id, confidence, detected_phrase=""):
    """Send alert to MQTT broker with buffer time"""
    global last_mqtt_time
    current_time = time.time()

    if current_time - last_mqtt_time < MQTT_BUFFER_SECONDS:
        print(f"MQTT message blocked: Waiting {MQTT_BUFFER_SECONDS - (current_time - last_mqtt_time):.1f}s for buffer")
        return False

    alert_data = {
        "timestamp": datetime.now().isoformat(),
        "alert_type": CLASS_LABELS[class_id],
        "confidence": float(confidence),
        "phrase": detected_phrase,
        "source": "audio"
    }
    try:
        result = client.publish(MQTT_TOPIC, json.dumps(alert_data), qos=2)
        result.wait_for_publish()
        if result.is_published():
            print(f"✓ MQTT Alert successfully published")
            print(f"  Details: {alert_data}")
            last_mqtt_time = time.time()  # Update after successful send
            return True
        else:
            print(f"! MQTT Alert may not have been delivered")
            return False
    except Exception as e:
        print(f"✗ Failed to send MQTT message: {e}")
        return False


# Configuration
SAMPLE_RATE = 16000
DURATION = 1.0
CHUNK_SIZE = int(SAMPLE_RATE * DURATION)
TFLITE_MODEL_PATH = "ML/model_quant.tflite"
VOSK_MODEL_PATH = "ML/vosk-model-small-en-us-0.15"
INPUT_SHAPE = (128, 100)
THRESHOLD = 0.7
COOLDOWN_SECONDS = 10  # Cooldown for detections
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

# Load TFLite Model
interpreter = tflite.Interpreter(model_path=TFLITE_MODEL_PATH)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

# Load Vosk Model
if not os.path.exists(VOSK_MODEL_PATH):
    print(f"Vosk model path {VOSK_MODEL_PATH} does not exist. Exiting.")
    exit(1)
vosk_model = Model(VOSK_MODEL_PATH)
recognizer = KaldiRecognizer(vosk_model, SAMPLE_RATE)


# Audio Device Selection
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

# Audio Queue
audio_queue = queue.Queue()

# Feature Extraction for TFLite
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


# TFLite Inference
def tflite_predict(features):
    interpreter.set_tensor(input_details[0]['index'], features)
    interpreter.invoke()
    return interpreter.get_tensor(output_details[0]['index'])


# Audio Processing Thread
def audio_processing_thread():
    last_trigger_time = 0
    while True:
        try:
            audio = audio_queue.get()
            start_time = time.time()

            if np.sqrt(np.mean(audio ** 2)) < 0.005:
                print("Skipping low energy frame (silence)")
                continue

            audio_cleaned = nr.reduce_noise(y=audio.flatten(), sr=SAMPLE_RATE)
            features = extract_mel_spectrogram(audio_cleaned)
            current_time = time.time()

            predictions = tflite_predict(features)
            tflite_detected = False

            # TFLite Detection
            for i, score in enumerate(predictions[0]):
                if i != 4 and score >= THRESHOLD:
                    if current_time - last_trigger_time > COOLDOWN_SECONDS:
                        class_label = CLASS_LABELS.get(i, f"Class {i}")
                        print(f"TFLite Detected! Class: {class_label} (Confidence: {score:.2f})")
                        if send_mqtt_alert(i, score):  # Check if MQTT was sent
                            last_trigger_time = current_time
                    tflite_detected = True
                    break

            # Vosk Fallback
            if not tflite_detected and current_time - last_trigger_time > COOLDOWN_SECONDS:
                if recognizer.AcceptWaveform(audio_cleaned.tobytes()):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").lower()
                    if text and any(keyword in text for keyword in KEYWORDS):
                        print(f"Vosk Detected: {text}")
                        if send_mqtt_alert(3, 0.75, text):  # Check if MQTT was sent
                            last_trigger_time = current_time

            print(f"Processing time: {1000 * (time.time() - start_time):.1f}ms")
            audio_queue.task_done()

        except Exception as e:
            print(f"Error: {e}")


# Audio Callback
def audio_callback(indata, frames, time, status):
    audio_queue.put(indata.copy().flatten())


# Main Function
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
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("Stopping...")


if __name__ == "__main__":
    main()