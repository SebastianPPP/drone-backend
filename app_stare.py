from flask import Flask, request, jsonify, render_template, Response
from datetime import datetime
from functools import wraps
import time
import json
import os

app = Flask(__name__)

# KONFIGURACJA BEZPIECZEŃSTWA
ADMIN_USERNAME = '1'
ADMIN_PASSWORD = '1'

# KONFIGURACJA BAZY DANYCH 
DB_FILE = "drones_state.json"
drones_db = {}

def save_db():
    '''
    Funkcja zapisuje aktualny stan słownika drones_db do pliku JSON.
    Wywoływana jest po każdej kluczowej zmianie (np. wgranie misji),
    aby w razie awarii serwera nie utracić danych.
    '''
    try:
        with open(DB_FILE, 'w') as f:
            json.dump(drones_db, f, indent=4)
        print("[SERVER] Stan bazy danych zapisany.")
    except Exception as e:
        print(f"[ERROR] Nie udało się zapisać bazy: {e}")

def load_db():
    '''
    Funkcja wczytuje stan z pliku JSON przy starcie serwera.
    Dzięki temu serwer "pamięta" drony i ich misje po ewentualnym restarcie.
    '''
    global drones_db
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                drones_db = json.load(f)
            print(f"[SERVER] Wczytano stan {len(drones_db)} dronów z pliku.")
        except Exception as e:
            print(f"[ERROR] Błąd odczytu bazy: {e}")
            drones_db = {}

def check_auth(username, password):
    '''
    Funkcja pomocnicza sprawdzająca poprawność loginu i hasła.
    '''
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

def authenticate():
    '''
    Funkcja wysyła nagłówek 401, który wymusza na przeglądarce
    wyświetlenie okienka logowania.
    '''
    return Response(
        'Wymagane logowanie do systemu C2.\n', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    '''
    Nakładka na endpointy. Sprawdza, czy użytkownik jest zalogowany.
    Jeśli nie - blokuje dostęp i żąda hasła.
    Chronimy tym panel operatora i wgrywanie misji.
    '''
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def get_drone_entry(drone_id):
    '''
    Zbieranie informacji o dronach.
    '''
    if drone_id not in drones_db:
        drones_db[drone_id] = {
            "telemetry": {},
            "assigned_role": "None", 
            "current_mission": None,
            "last_seen": 0
        }
    return drones_db[drone_id]

@app.route("/")
@requires_auth
def index():
    '''
    Główny widok strony.
    Jest chroniony hasłem (@requires_auth), aby nikt obcy nie wszedł.
    '''
    return render_template("index.html")

@app.route("/api/telemetry", methods=["GET", "POST"])
def telemetry():
    '''
    Główny punkt komunikacji DRON <-> SERWER.
    POST: Dron wysyła telemetrię, serwer odsyła rozkazy.
    GET: Frontend pobiera listę dronów do mapy.
    '''
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
            "role": data.get("role", "None"),
            "mission_status": data.get("mission_status", "nothing"),
            "next_waypoints": data.get("next_waypoints", []),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        entry["last_seen"] = time.time()
        
        response_payload = {
            "role": entry["assigned_role"],
            "mission": entry["current_mission"]
        }
        
        return jsonify(response_payload), 200

    all_telemetry = []
    for d_id, data in drones_db.items():
        if data["telemetry"]:
            telem_copy = data["telemetry"].copy()
            telem_copy["server_assigned_role"] = data["assigned_role"]
            is_online = (time.time() - data["last_seen"]) < 10 
            telem_copy["online"] = is_online
            all_telemetry.append(telem_copy)
    return jsonify(all_telemetry)

@app.route("/api/mission/upload", methods=["POST"])
@requires_auth
def upload_mission():
    '''
    Endpoint do wgrywania misji przez operatora.
    WYMAGA HASŁA.
    Po przypisaniu misji następuje zapis bazy do pliku (save_db).
    '''
    data = request.get_json()
    drones_payload = data.get("drones", {})
    
    saved_ids = []
    
    for drone_id, mission_config in drones_payload.items():
        entry = get_drone_entry(drone_id)
        
        entry["current_mission"] = {
            "id": mission_config.get("mission_id"),
            "waypoints": mission_config.get("waypoints")
        }
        
        if "role" in mission_config:
            entry["assigned_role"] = mission_config["role"]
            
        saved_ids.append(drone_id)
        print(f"[SERVER] Wgrano misję i rolę '{entry['assigned_role']}' dla {drone_id}")

    save_db()

    return jsonify({
        "status": "STORED",
        "drones": saved_ids
    })

@app.route("/api/mission/stop", methods=["POST"])
@requires_auth
def stop_mission():
    '''
    Awaryjny STOP.
    WYMAGA HASŁA (@requires_auth).
    Czyści misje i zapisuje ten stan do pliku, żeby po restarcie drony nie ruszyły same.
    '''
    data = request.get_json()
    target_drones = data.get("drones", [])
    
    if not target_drones:
        target_drones = list(drones_db.keys())

    for drone_id in target_drones:
        entry = get_drone_entry(drone_id)
        entry["current_mission"] = None
        entry["assigned_role"] = "None"
        print(f"[SERVER] STOP dla {drone_id}")

    save_db() 

    return jsonify({"status": "STOPPED"})

if __name__ == "__main__":
    load_db()
    app.run(host='0.0.0.0', port=5000, debug=True)