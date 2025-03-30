import paho.mqtt.client as mqtt
import json
import time
from datetime import datetime

broker = "test.mosquitto.org"
port = 1883
topic = "nurse/dashboard"

client = mqtt.Client()
client.connect(broker, port, 60)

alerts = [
    {
        "priority": "HIGH",
        "alert_type": "Fall Detected",
        "source": "video",
        "details": "Patient has fallen and is unresponsive"
    },
    {
        "priority": "MEDIUM",
        "alert_type": "Loud Noise",
        "source": "audio",
        "details": "Patient may be calling for help"
    },
    {
        "priority": "LOW",
        "alert_type": "Slight Movement",
        "source": "proximity",
        "details": "Patient adjusted position slightly"
    }
]

for alert in alerts:
    alert["timestamp"] = datetime.now().isoformat()
    client.publish(topic, json.dumps(alert))
    print(f"✅ Published {alert['priority']} priority alert")
    time.sleep(5)  # 5-second gap

client.disconnect()
print("🔌 Disconnected from broker")
