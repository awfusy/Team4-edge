import os
import librosa
import numpy as np
import pandas as pd
import random

output_csv = "features.csv"
root_dir = "output"

# Initialize lists to store features and labels
features_list = []
labels_list = []

# Label mapping
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

# Constants
FIXED_TIME_FRAMES = 100
MAX_NOISE_SAMPLES = 360  # optional

# Walk through the directory and process .wav files
for folder_name in os.listdir(root_dir):
    folder_path = os.path.join(root_dir, folder_name)

    if not os.path.isdir(folder_path):
        continue

    output_wav_folder = os.path.join(folder_path, "output_wav")
    if not os.path.exists(output_wav_folder) or not os.path.isdir(output_wav_folder):
        print(f"Skipping folder: {folder_name} (missing 'output_wav' subfolder)")
        continue

    label = label_map.get(folder_name, -1)
    if label == -1:
        print(f"Skipping folder: {folder_name} (unknown label)")
        continue

    # Optional subsample noise class to balance
    file_list = os.listdir(output_wav_folder)
    if label == 4 and len(file_list) > MAX_NOISE_SAMPLES:
        file_list = random.sample(file_list, MAX_NOISE_SAMPLES)

    for file_name in file_list:
        if file_name.endswith(".wav"):
            wav_path = os.path.join(output_wav_folder, file_name)
            y, sr = librosa.load(wav_path, sr=16000)

            # Feature extraction
            S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128)
            log_mel_spectrogram = librosa.power_to_db(S, ref=np.max)

            # Pad or truncate
            if log_mel_spectrogram.shape[1] > FIXED_TIME_FRAMES:
                log_mel_spectrogram = log_mel_spectrogram[:, :FIXED_TIME_FRAMES]
            elif log_mel_spectrogram.shape[1] < FIXED_TIME_FRAMES:
                pad_width = FIXED_TIME_FRAMES - log_mel_spectrogram.shape[1]
                log_mel_spectrogram = np.pad(log_mel_spectrogram, ((0, 0), (0, pad_width)), mode='constant')

            # Flatten and append
            flattened_feature = log_mel_spectrogram.flatten()
            features_list.append(flattened_feature)
            labels_list.append(label)

# Save to CSV
features_df = pd.DataFrame(features_list)
features_df["label"] = labels_list
features_df.to_csv(output_csv, index=False)

print(f"✅ Features saved to {output_csv}")
df = pd.read_csv(output_csv)
print(df["label"].value_counts().sort_index())
