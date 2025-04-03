# AI Enabled Smart Patient Assistance System with Multi-Sensor Monitoring for Enhanced Patient Care and Emergency Response

AI-Enabled Smart Patient Assistance System
A real-time, event-driven IoT healthcare monitoring system powered by edge computing. This system leverages voice detection, pose estimation, and proximity sensing to detect patient emergencies such as falls, calls for help, or leaving the bed — without requiring physical call buttons.

Materials Needed

- 4x Raspberry Pi devices (for Audio, Camera, Central Hub, Ultrasonic)
- MicroSD cards (with Raspberry Pi OS installed)
- USB Webcam (for fall detection)
- USB Microphone (for voice detection)
- 3x Ultrasonic sensors (for bed proximity sensing)
- Internet connection (for MQTT communication)

# Project Setup

1. Prepare Each Raspberry Pi
Assign roles to each Pi:
  - Audio Pi → wake_word.py
  - Camera Pi → falldetection4.py
  - Ultrasonic Pi → Ultrasonic_final.py
  - Central Hub Pi → optimised_hub_final.py

2. Set Up Python Environment on Each Pi

Step into your working directory
cd ~/your_project_folder/

Create a virtual environment
python3 -m venv myenv

Activate the environment
source myenv/bin/activate

Install dependencies
pip install -r requirements.txt -r video_requirements.txt
Repeat on each Pi according to its role.

3. Transfer the Relevant Scripts to Each Pi
Use scp or USB to transfer the appropriate Python files:

  - Audio Pi → wake_word.py, model_quant.tflite, vosk-model-small-en-us-0.15
  - Camera Pi → falldetection4.py
  - Ultrasonic Pi → Ultrasonic_final.py
  - Central Hub	→ optimised_hub_final.py
  - Flask App	→ edge_flask/app.py, templates, static files

4. Enable MQTT Broker on the Central Hub Pi

#Ensure the broker is running and accessible to all other Pis.
sudo systemctl enable mosquitto
sudo systemctl start mosquitto

 5. Update IP Addresses in Code
Edit the MQTT broker address in all Pi scripts to point to the Central Hub Pi’s IP address:

MQTT_BROKER = "192.168.xx.xxx"  # Replace with actual IP

Audio Model Setup (Audio Pi)
1. Convert .mp3 audio samples to .wav:
    python file_conversion.py
   
2. Process audio and extract features:
    python audio_processing.py
   
3. Train the model and generate tflite.model:
    python audio_model.py
   
Camera Setup (Camera Pi)
1. Connect the USB webcam.
2. Position the camera perpendicular to the bed, slightly elevated to capture full-body view.
3. Start the detection script:
    python3 falldetection4.py
   
Run the Nurse Dashboard (Flask App)
1. Navigate to the Flask project folder:
    cd edge_flask/
   
2. Ensure your virtual environment is active and install Flask dependencies if needed:
    pip install -r requirements.txt
   
3. Run the dashboard:
    python app.py
   
4. Access the dashboard in your browser:
    http://<your_laptop_ip>:5000
   
Usage Flow
Proximity Pi → Detects bed exit → Sends MQTT alert → Central Hub activates camera.
Audio Pi → Detects wake words like "Help" → Sends alert → Triggers camera and dashboard notification.
Camera Pi → Analyzes posture → Detects falls → Sends real-time video and MQTT alert.
Flask Dashboard → Displays alert messages, plays sound, and streams live video.

# Technologies Used
- Python 3.x
- Flask + Flask-SocketIO
- OpenCV + MediaPipe
- Vosk + TensorFlow Lite
- MQTT (Mosquitto Broker)
- Socket.IO for real-time communication

# Project Architecture

![Project System Architecture_Team4](https://github.com/user-attachments/assets/100f32bd-a4f0-44ba-8791-9e0be5d60df2)
