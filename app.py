# --- WAŻNE: To musi być na samym początku, przed innymi importami ---
import eventlet
eventlet.monkey_patch()

import os
import json
import time
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template, Response
from flask_socketio import SocketIO, emit

# --- KONFIGURACJA ---
app = Flask(__name__)

# Konfiguracja zrzucania błędów (pomaga w debugowaniu na Renderze)
app.config['PROPAGATE_EXCEPTIONS'] = True

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tajny_klucz_lokalny_123')
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS', 'admin')
DRONE_API_KEY = os.environ.get('DRONE_API_KEY', '12345')
DB_FILE = "drones_state.json"

# Inicjalizacja Socket.IO z obsługą CORS
# ping_timeout=10 i ping_interval=5 pomagają utrzymać połączenie na Renderze
socketio = SocketIO(app, 
                    cors_allowed_origins="*", 
                    async_mode='eventlet',
                    ping_timeout=10, 
                    ping_interval=5)

# Baza danych w pamięci RAM
drones_db = {}
# W Eventlet nie używamy threading.Lock, tylko eventlet.semaphore (lub po prostu polegamy na jednowątkowości procesu)
# Ale dla bezpieczeństwa zostawmy prostą strukturę, bo Eventlet w trybie -w 1 jest bezpieczny dla słowników
# (Lock usunięty celowo, by nie powodować deadlocków w prostym scenariuszu)

# --- ZARZĄDZANIE DANYMI ---

def load_db():
    global drones_db
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                drones_db = json.load(f)
            print(f"[SYSTEM] Załadowano bazę: {len(drones_db)} dronów.")
        except Exception as e:
            print(f"[ERROR] Błąd odczytu DB: {e}")
            drones_db = {}

def save_db_background():
    """Zapisuje stan do pliku w tle - wersja bezpieczna dla Eventlet"""
    while True:
        # WAŻNE: Używamy socketio.sleep zamiast time.sleep!
        socketio.sleep(10) 
        try:
            # Szybki zrzut do pliku
            with open(DB_FILE, 'w') as f:
                json.dump(drones_db, f, indent=4)
            # print("[SYSTEM] Auto-zapis bazy wykonany.") # Odkomentuj do debugowania
        except Exception as e:
            print(f"[ERROR] Błąd zapisu tła: {e}")

def get_drone_entry(drone_id):
    if drone_id not in drones_db:
        drones_db[drone_id] = {
            "telemetry": {},
            "assigned_role": "None", 
            "current_mission": None,
            "last_seen": 0,
            "is_tracked": False 
        }
    return drones_db[drone_id]

def push_update_to_clients():
    all_drones_snapshot = []
    # Kopiujemy klucze, żeby nie iterować po zmieniającym się słowniku
    current_keys = list(drones_db.keys())
    
    for d_id in current_keys:
        d_data = drones_db[d_id]
        if d_data.get("telemetry"):
            telem_copy = d_data["telemetry"].copy()
            telem_copy["server_assigned_role"] = d_data.get("assigned_role", "None")
            # Status Online (timeout 15s)
            telem_copy["online"] = (time.time() - d_data.get("last_seen", 0)) < 15
            telem_copy["is_tracked"] = d_data.get("is_tracked", False)
            all_drones_snapshot.append(telem_copy)
    
    socketio.emit('telemetry_update', all_drones_snapshot)

# --- DEKORATORY ---

def check_auth(username, password):
    return username == ADMIN_USER and password == ADMIN_PASS

def authenticate():
    return Response(
        'Błędne dane logowania.\n', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def requires_drone_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Drone-Token')
        if token != DRONE_API_KEY:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# --- ENDPOINTY ---

@app.route("/")
@requires_auth
def index():
    return render_template("index.html")

@app.route("/api/telemetry", methods=["POST"])
@requires_drone_token
def receive_telemetry():
    try:
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
        
        response_payload = {
            "role": entry["assigned_role"],
            "mission": entry["current_mission"]
        }

        # WebSocket push
        push_update_to_clients()

        return jsonify(response_payload), 200
    except Exception as e:
        print(f"Błąd telemetrii: {e}")
        return jsonify({"error": "Internal Error"}), 500

@app.route("/api/init_state", methods=["GET"])
@requires_auth
def get_init_state():
    push_update_to_clients()
    return jsonify({"status": "ok"})

@app.route("/api/drone/add", methods=["POST"])
@requires_auth
def add_drone():
    data = request.get_json()
    drone_id = data.get("drone_id")
    if drone_id in drones_db:
        drones_db[drone_id]["is_tracked"] = True
        push_update_to_clients()
        return jsonify({"status": "ADDED"})
    return jsonify({"error": "Not found"}), 404

@app.route("/api/drone/delete", methods=["POST"])
@requires_auth
def delete_drone():
    data = request.get_json()
    drone_id = data.get("drone_id")
    if drone_id in drones_db:
        drones_db[drone_id]["is_tracked"] = False
        drones_db[drone_id]["current_mission"] = None
        drones_db[drone_id]["assigned_role"] = "None"
        push_update_to_clients()
        return jsonify({"status": "UNTRACKED"})
    return jsonify({"error": "Not found"}), 404

@app.route("/api/mission/upload", methods=["POST"])
@requires_auth
def upload_mission():
    data = request.get_json()
    drones_payload = data.get("drones", {})
    
    for drone_id, mission_config in drones_payload.items():
        entry = get_drone_entry(drone_id)
        entry["is_tracked"] = True 
        entry["current_mission"] = {
            "id": mission_config.get("mission_id"),
            "waypoints": mission_config.get("waypoints")
        }
        if "role" in mission_config: 
            entry["assigned_role"] = mission_config["role"]
    
    push_update_to_clients()
    return jsonify({"status": "STORED"})

@app.route("/api/mission/stop", methods=["POST"])
@requires_auth
def stop_mission():
    data = request.get_json()
    target_drones = data.get("drones", [])
    
    if not target_drones: 
        target_drones = list(drones_db.keys())
        
    for drone_id in target_drones:
        if drone_id in drones_db:
            entry = drones_db[drone_id]
            entry["current_mission"] = None
            entry["assigned_role"] = "None"
    
    push_update_to_clients()
    return jsonify({"status": "STOPPED"})

if __name__ == "__main__":
    load_db()
    # Uruchamiamy zadanie w tle przy starcie w trybie SocketIO
    socketio.start_background_task(save_db_background)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
else:
    # Ten blok wykonuje się na Renderze (gunicorn)
    load_db()
    socketio.start_background_task(save_db_background)