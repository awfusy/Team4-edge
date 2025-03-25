# yamnet_classifier_training.py not using, the accuracy is lower than TFL models

import os
import librosa
import numpy as np
import tensorflow as tf
import tensorflow_hub as hub
from sklearn.model_selection import train_test_split
from tensorflow.keras.utils import to_categorical
from tensorflow.keras import models, layers
import random
import warnings

warnings.filterwarnings("ignore", category=UserWarning)

# -----------------------------
# Config
# -----------------------------
SAMPLE_RATE = 16000
SNR = 10  # Signal-to-noise ratio
NUM_CLASSES = 5
background_noise_dir = "output/noise/output_wav"

# -----------------------------
# Label Mapping (grouped)
# -----------------------------
label_map = {
    "help": 0,
    "help_me": 0,
    "somebody_help": 0,
    "please_help": 0,

    "call_nurse": 1,
    "doctor_help": 1,
    "emergency": 1,
    "urgent_help": 1,
    "call_doctor": 1,

    "this_hurts": 2,
    "help_it_hurts": 2,
    "I'm_in_pain": 2,
    "it_hurts": 2,

    "assistance_needed": 3,
    "can_someone_help_me": 3,
    # "medical_assistance": 3,
    # "I'm_dizzy": 3,
    # "I_can't_breathe": 3,
    # "I_feel_sick": 3,
    "I_need_a_doctor": 3,
    "I_need_a_nurse": 3,
    "I_need_help": 3,
    "nurse_help": 3,
    "nurse_please": 3,
    "please_hurry": 3,
    "quick_help": 3,

    "noise": 4,
    "no": 4,
    "yes": 4,
    "right": 4
}

# -----------------------------
# Load YAMNet from TF Hub
# -----------------------------
print("Loading YAMNet from TensorFlow Hub...")
yamnet_model = hub.load("https://tfhub.dev/google/yamnet/1")

# -----------------------------
# Background noise mixing helper
# -----------------------------
def mix_background_noise(audio, sr, noise_dir, snr_db=10):
    noise_files = [f for f in os.listdir(noise_dir) if f.endswith(".wav")]
    if not noise_files:
        return audio
    noise_path = os.path.join(noise_dir, random.choice(noise_files))
    noise_audio, _ = librosa.load(noise_path, sr=sr)
    if len(noise_audio) < len(audio):
        noise_audio = np.pad(noise_audio, (0, len(audio) - len(noise_audio)))
    else:
        noise_audio = noise_audio[:len(audio)]
    audio_rms = np.sqrt(np.mean(audio ** 2))
    noise_rms = np.sqrt(np.mean(noise_audio ** 2))
    if noise_rms == 0:
        return audio
    desired_noise_rms = audio_rms / (10 ** (snr_db / 20))
    noise_audio *= (desired_noise_rms / noise_rms)
    mixed = audio + noise_audio
    return mixed / np.max(np.abs(mixed))

# -----------------------------
# Dataset Preparation
# -----------------------------
print("Extracting embeddings...")
features = []
labels = []
root_dir = "output"

for folder in os.listdir(root_dir):
    folder_path = os.path.join(root_dir, folder)
    if not os.path.isdir(folder_path):
        continue
    if folder not in label_map:
        print(f"Skipping folder: {folder} (not in label_map)")
        continue

    label = label_map[folder]
    wav_dir = os.path.join(folder_path, "output_wav")
    if not os.path.exists(wav_dir):
        print(f"No output_wav in {folder}")
        continue

    files = [f for f in os.listdir(wav_dir) if f.endswith(".wav")]
    for file in files:
        file_path = os.path.join(wav_dir, file)
        try:
            y, sr = librosa.load(file_path, sr=SAMPLE_RATE)
            y = y[:SAMPLE_RATE]

            scores, embeddings, _ = yamnet_model(y)
            emb = np.mean(embeddings.numpy(), axis=0)
            features.append(emb)
            labels.append(label)
        except Exception as e:
            print(f"Error in {file_path}: {e}")

# -----------------------------
# Convert to Arrays
# -----------------------------
X = np.array(features, dtype=np.float32)
y = to_categorical(labels, num_classes=NUM_CLASSES)

# -----------------------------
# Train/Test Split
# -----------------------------
X_train, X_test, y_train, y_test = train_test_split(X, y, stratify=np.argmax(y, axis=1), test_size=0.2, random_state=42)

# -----------------------------
# Classifier Model
# -----------------------------
print("Training classifier model...")
model = models.Sequential([
    layers.Input(shape=(1024,)),
    layers.Dense(128, activation='relu'),
    layers.Dropout(0.3),
    layers.Dense(64, activation='relu'),
    layers.Dense(NUM_CLASSES, activation='softmax')
])

model.compile(optimizer='adam',
              loss=tf.keras.losses.CategoricalCrossentropy(label_smoothing=0.05),
              metrics=['accuracy'])

history = model.fit(
    X_train, y_train,
    validation_split=0.2,
    epochs=25,
    batch_size=32
)

# -----------------------------
# Evaluation
# -----------------------------
loss, acc = model.evaluate(X_test, y_test)
print(f"Test Accuracy: {acc:.2f}")

# -----------------------------
# Save label_map
# -----------------------------
with open("label_map.txt", "w") as f:
    for key, val in sorted(label_map.items(), key=lambda x: x[1]):
        f.write(f"{val},{key}\n")

# -----------------------------
# Convert to TFLite
# -----------------------------
print("Converting to TFLite (FP16)...")
converter = tf.lite.TFLiteConverter.from_keras_model(model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.target_spec.supported_types = [tf.float16]
tflite_model = converter.convert()

with open("yamnet_classifier.tflite", "wb") as f:
    f.write(tflite_model)

print("Done! Saved: yamnet_classifier.tflite + label_map.txt")
