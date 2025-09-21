import requests
import time

BASE_URL = "http://127.0.0.1:5000"

# Lista dronów startowych
drones = [
    {"drone_id": "DRON-1", "lat": 52.1, "lon": 21.0, "alt": 120, "battery": 85},
    {"drone_id": "DRON-2", "lat": 52.2, "lon": 21.1, "alt": 100, "battery": 90},
    {"drone_id": "DRON-3", "lat": 52.15, "lon": 21.05, "alt": 110, "battery": 75}
]

# Stan dronów
drone_states = {d["drone_id"]: {"mission": None, "current_point": 0, "completed": False} for d in drones}


def send_telemetry(drone):
    """Wyślij telemetry drona na serwer"""
    r = requests.post(f"{BASE_URL}/api/telemetry", json=drone)
    if r.status_code != 200:
        print(f"{drone['drone_id']} telemetry error:", r.status_code, r.text)


def fetch_missions():
    """Pobierz aktualne misje dla dronów"""
    try:
        r = requests.get(f"{BASE_URL}/api/mission/current")
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print("Błąd pobierania misji:", e)
    return {}


def confirm_mission(drone_id):
    """Potwierdzenie odebrania misji"""
    payload = {"droneId": drone_id, "status": "received"}
    r = requests.post(f"{BASE_URL}/api/mission/status", json=payload)
    if r.status_code == 200:
        print(f"{drone_id} potwierdził odebranie misji")


def move_drone(drone, target_point):
    """Przesuń drona na punkt misji i wyślij telemetry"""
    lat, lon = target_point  # już w formacie [lat, lon]
    drone["lat"] = lon
    drone["lon"] = lat
    send_telemetry(drone)
    print(f"{drone['drone_id']} przesunięty na punkt: {target_point}")


# Pętla symulacji
while True:
    missions = fetch_missions()

    for drone in drones:
        drone_id = drone["drone_id"]

        # Dron ma przypisaną misję
        if drone_id in missions:
            mission_path = missions[drone_id]

            # Jeśli dron jeszcze nie rozpoczął misji
            if drone_states[drone_id]["mission"] is None:
                drone_states[drone_id]["mission"] = mission_path
                drone_states[drone_id]["current_point"] = 0
                drone_states[drone_id]["completed"] = False
                confirm_mission(drone_id)

            # Wykonaj trasę punkt po punkcie
            idx = drone_states[drone_id]["current_point"]
            if idx < len(mission_path):
                move_drone(drone, mission_path[idx])
                drone_states[drone_id]["current_point"] += 1
            else:
                # Misja zakończona, dron pozostaje w ostatnim punkcie
                if not drone_states[drone_id]["completed"]:
                    print(f"{drone_id} zakończył misję")
                    drone_states[drone_id]["completed"] = True
                send_telemetry(drone)

        else:
            # Brak misji → wysyłamy telemetry z obecnego miejsca
            send_telemetry(drone)

    time.sleep(1)
