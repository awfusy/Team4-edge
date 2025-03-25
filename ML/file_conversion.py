# This is for converting mp3 to wav
from pydub import AudioSegment
import os
import shutil

root_dir = "output"

# Walk through the directory and its subfolders
for root, dirs, files in os.walk(root_dir):
    # Create an "output_wav" folder in the current subfolder
    output_wav_dir = os.path.join(root, "output_wav")
    os.makedirs(output_wav_dir, exist_ok=True)

    for file in files:
        if file.endswith(".mp3"):
            mp3_path = os.path.join(root, file)

            # Construct the corresponding WAV file path inside the "output_wav" folder
            wav_filename = os.path.splitext(file)[0] + ".wav"
            wav_path = os.path.join(output_wav_dir, wav_filename)

            # Skip conversion if the WAV file already exists in the "output_wav" folder
            if os.path.exists(wav_path):
                print(f"Skipping {mp3_path} (WAV already exists in output_wav)")
                continue

            # Convert MP3 to WAV
            print(f"Converting {mp3_path} to {wav_path}")
            try:
                audio = AudioSegment.from_mp3(mp3_path)

                # Standardize audio parameters: 16 kHz sample rate, mono channel, 16-bit depth
                audio = audio.set_frame_rate(16000).set_channels(1)
                audio.export(wav_path, format="wav")
            except Exception as e:
                print(f"Error converting {mp3_path}: {e}")

        elif file.endswith(".wav"):
            # Move pre-existing WAV files to the "output_wav" folder
            wav_path = os.path.join(root, file)
            new_wav_path = os.path.join(output_wav_dir, file)

            if not os.path.exists(new_wav_path):  # Avoid overwriting
                print(f"Moving {wav_path} to {new_wav_path}")
                shutil.move(wav_path, new_wav_path)
            else:
                print(f"Skipping {wav_path} (already exists in output_wav)")

print("Conversion and organization complete!")