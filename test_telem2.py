import requests
import time
from datetime import datetime
import random

API_URL = "http://localhost:5000/api/telemetry"
DRONE_ID = "drone_test_2"

# Wysyłaj dane przez 10 sekund
for i in range(100):
    lat = 52.0 + random.uniform(-0.01, 0.01)
    lon = 21.0 + random.uniform(-0.01, 0.01)
    data = {
        "drone_id": DRONE_ID,
        "lat": lat,
        "lon": lon,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "timestamp_unix": time.time()
    }
    try:
        response = requests.post(API_URL, json=data)
        print(f"[{datetime.now()}] Sent: {data} Status: {response.status_code}")
    except Exception as e:
        print(f"[{datetime.now()}] Request failed: {e}")
    time.sleep(1)

print("=== Drone went silent ===")
# Nie wysyła danych przez 20 sekund
time.sleep(20)
print("=== Done ===")
