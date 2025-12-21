from flask import Flask, request, jsonify, render_template
from datetime import datetime
import time

app = Flask(__name__)

# --- BAZA DANYCH W PAMIĘCI (RAM) ---
# Przechowuje aktualny stan dla każdego drona
drones_db = {}

# Struktura rekordu w drones_db:
# drones_db["drone_1"] = {
#     "telemetry": { ... },
#     "current_mission": { "mission_id": "...", "waypoints": [...] },  # Ostatnia wgrana misja
#     "pending_command": None,  # Np. "STOP", "RETURN" - komenda do pobrania przez drona
#     "last_seen": timestamp
# }

def get_drone_entry(drone_id):
    if drone_id not in drones_db:
        drones_db[drone_id] = {
            "telemetry": {},
            "current_mission": None,
            "pending_command": None,
            "last_seen": 0
        }
    return drones_db[drone_id]

@app.route("/")
def index():
    return render_template("index.html")

# ==========================================
# 1. ENDPOINTY DLA FRONTENDU (Panel WWW)
# ==========================================

# Odbieranie danych telemetrycznych (może być wysyłane przez drona, a czytane przez JS)
@app.route("/api/telemetry", methods=["GET", "POST"])
def telemetry():
    # DRON -> SERWER: Dron wysyła swoją pozycję
    if request.method == "POST":
        data = request.get_json()
        drone_id = data.get("drone_id")
        if not drone_id:
            return jsonify({"error": "No drone_id"}), 400
        
        entry = get_drone_entry(drone_id)
        entry["telemetry"] = {
            "drone_id": drone_id,
            "lat": data.get("lat"),
            "lon": data.get("lon"),
            "alt": data.get("alt", 0),
            "battery": data.get("battery", 0),
            "roll": data.get("roll", 0),
            "pitch": data.get("pitch", 0),
            "yaw": data.get("yaw", 0),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        entry["last_seen"] = time.time()
        return jsonify({"status": "ok"}), 200

    # FRONTEND -> SERWER: JS pobiera listę wszystkich dronów do wyświetlenia na mapie
    all_telemetry = []
    for d_id, data in drones_db.items():
        if data["telemetry"]:
            all_telemetry.append(data["telemetry"])
    return jsonify(all_telemetry)


# Frontend wysyła misję -> Serwer zapisuje ją "na półce"
@app.route("/api/mission/upload", methods=["POST"])
def upload_mission():
    data = request.get_json()
    drones_payload = data.get("drones", {})
    
    saved_ids = []
    
    for drone_id, mission_data in drones_payload.items():
        entry = get_drone_entry(drone_id)
        # Nadpisujemy aktualną misję nową
        entry["current_mission"] = mission_data
        # Czyścimy ewentualne komendy stop, bo wchodzi nowa misja
        entry["pending_command"] = "NEW_MISSION_AVAILABLE" 
        saved_ids.append(drone_id)
        
        print(f"💾 [SERVER] Zapisano misję dla {drone_id} (ID: {mission_data.get('mission_id')})")

    return jsonify({
        "status": "STORED",
        "message": "Misja zapisana na serwerze. Czekam aż dron ją pobierze.",
        "drones": saved_ids
    })


# Frontend wysyła STOP -> Serwer ustawia flagę
@app.route("/api/mission/stop", methods=["POST"])
def stop_mission():
    data = request.get_json()
    target_drones = data.get("drones", [])
    
    if not target_drones:
        target_drones = list(drones_db.keys())

    for drone_id in target_drones:
        entry = get_drone_entry(drone_id)
        entry["pending_command"] = "STOP" # Flaga dla drona
        # Opcjonalnie usuwamy misję z pamięci, żeby dron nie wznowił
        entry["current_mission"] = None
        print(f"🛑 [SERVER] Ustawiono flagę STOP dla {drone_id}")

    return jsonify({"status": "FLAG_SET", "command": "STOP"})


# ==========================================
# 2. ENDPOINTY DLA DRONA (To tutaj dron pobiera dane)
# ==========================================

# Dron odpytuje ten adres np. co 1s: GET /api/drone/sync/drone_1
@app.route("/api/drone/sync/<drone_id>", methods=["GET"])
def drone_sync(drone_id):
    if drone_id not in drones_db:
        return jsonify({"command": "None", "mission": None})

    entry = drones_db[drone_id]
    
    response = {
        "command": entry["pending_command"], # np. "STOP", "NEW_MISSION_AVAILABLE" lub None
        "mission": None
    }
    
    # Jeśli jest nowa misja i dron o nią pyta (lub po prostu zawsze zwracamy aktualną)
    if entry["current_mission"]:
        response["mission"] = entry["current_mission"]

    # Po pobraniu komendy STOP, możemy ją wyczyścić (żeby nie stopował w kółko), 
    # ale bezpieczniej trzymać, dopóki dron nie potwierdzi (tu wersja uproszczona):
    if entry["pending_command"] == "NEW_MISSION_AVAILABLE":
        entry["pending_command"] = None # Reset flagi powiadomienia

    return jsonify(response)


if __name__ == "__main__":
    # Host 0.0.0.0 pozwala na dostęp z sieci lokalnej (dron widzi serwer po IP)
    app.run(host='0.0.0.0', port=5000, debug=True)