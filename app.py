from flask import Flask, request, jsonify, render_template
from datetime import datetime
import time

app = Flask(__name__)

# --- BAZA DANYCH W PAMIĘCI (RAM) ---
# Struktura:
# drones_db["skimmer1"] = {
#     "telemetry": { ... },       # To co dron zgłasza (lat, lon, battery, next_waypoints, reported_role)
#     "assigned_role": "None",    # Rola nadana przez serwer (Leader/Follower)
#     "current_mission": None,    # Obiekt misji: { "id": "...", "waypoints": [...] }
#     "last_seen": timestamp
# }
drones_db = {}

def get_drone_entry(drone_id):
    if drone_id not in drones_db:
        drones_db[drone_id] = {
            "telemetry": {},
            "assigned_role": "None", 
            "current_mission": None,
            "last_seen": 0
        }
    return drones_db[drone_id]

@app.route("/")
def index():
    return render_template("index.html")

# ==========================================
# GŁÓWNY ENDPOINT KOMUNIKACJI (Dwukierunkowy)
# ==========================================
@app.route("/api/telemetry", methods=["GET", "POST"])
def telemetry():
    # 1. DRON -> SERWER (POST)
    # Dron wysyła swój stan, a serwer w odpowiedzi odsyła rozkazy (rolę i misję)
    if request.method == "POST":
        data = request.get_json()
        drone_id = data.get("drone_id")
        if not drone_id:
            return jsonify({"error": "No drone_id"}), 400
        
        entry = get_drone_entry(drone_id)
        
        # Zapisujemy to, co przysłał dron
        entry["telemetry"] = {
            "drone_id": drone_id,
            "lat": data.get("lat"),
            "lon": data.get("lon"),
            "alt": data.get("alt", 0),
            "battery": data.get("battery", 0),
            "roll": data.get("roll", 0),
            "pitch": data.get("pitch", 0),
            "yaw": data.get("yaw", 0),
            # Nowe pola z drone_telem.py
            "role": data.get("role", "None"), # Rola zgłaszana przez drona
            "mission_status": data.get("mission_status", "nothing"),
            "next_waypoints": data.get("next_waypoints", []),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        entry["last_seen"] = time.time()
        
        # PRZYGOTOWANIE ODPOWIEDZI DLA DRONA
        # Dron oczekuje JSON-a z kluczami: "role" i "mission"
        response_payload = {
            "role": entry["assigned_role"],   # Serwer narzuca rolę (np. leader)
            "mission": entry["current_mission"] # Serwer wysyła misję (lub null)
        }
        
        return jsonify(response_payload), 200

    # 2. FRONTEND -> SERWER (GET)
    # JS pobiera listę wszystkich dronów do wyświetlenia na mapie
    all_telemetry = []
    for d_id, data in drones_db.items():
        if data["telemetry"]:
            # Doklejamy assigned_role do podglądu, żeby widzieć na mapie co serwer kazał robić
            telem_copy = data["telemetry"].copy()
            telem_copy["server_assigned_role"] = data["assigned_role"]
            all_telemetry.append(telem_copy)
    return jsonify(all_telemetry)


# ==========================================
# ZARZĄDZANIE MISJĄ
# ==========================================
@app.route("/api/mission/upload", methods=["POST"])
def upload_mission():
    data = request.get_json()
    drones_payload = data.get("drones", {})
    
    saved_ids = []
    
    for drone_id, mission_config in drones_payload.items():
        entry = get_drone_entry(drone_id)
        
        # Frontend wysyła teraz strukturę: { "mission_id": "...", "waypoints": [...], "role": "..." }
        entry["current_mission"] = {
            "id": mission_config.get("mission_id"),
            "waypoints": mission_config.get("waypoints")
        }
        
        # Ustawiamy rolę zadaną przez operatora (Frontend)
        if "role" in mission_config:
            entry["assigned_role"] = mission_config["role"]
            
        saved_ids.append(drone_id)
        print(f"💾 [SERVER] Wgrano misję i rolę '{entry['assigned_role']}' dla {drone_id}")

    return jsonify({
        "status": "STORED",
        "drones": saved_ids
    })


@app.route("/api/mission/stop", methods=["POST"])
def stop_mission():
    """Awaryjne czyszczenie misji."""
    data = request.get_json()
    target_drones = data.get("drones", [])
    
    if not target_drones:
        target_drones = list(drones_db.keys())

    for drone_id in target_drones:
        entry = get_drone_entry(drone_id)
        # Usuwamy misję -> dron otrzyma null w odpowiedzi na telemetry i (zależnie od logiki) się zatrzyma
        entry["current_mission"] = None
        entry["assigned_role"] = "None"
        print(f"🛑 [SERVER] STOP dla {drone_id}")

    return jsonify({"status": "STOPPED"})


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)