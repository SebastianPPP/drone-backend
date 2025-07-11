import requests
import time
from datetime import datetime
import random

API_URL = "https://drone-backend-2-1mwz.onrender.com/api/telemetry"
DRONE_ID = "drone_test_2"

lat = 51.5
lon = 19.0

while True:
    # Symuluj lekki ruch
    lat += random.uniform(-0.0005, 0.0005)
    lon += random.uniform(-0.0005, 0.0005)

    data = {
        "drone_id": DRONE_ID,
        "lat": round(lat, 6),
        "lon": round(lon, 6)
    }

    try:
        response = requests.post(API_URL, json=data)
        print(f"[{datetime.now()}] Sent: {data} Status: {response.status_code}")
    except Exception as e:
        print("Request failed:", e)

    time.sleep(1)
