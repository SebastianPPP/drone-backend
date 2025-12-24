import os
import json
import threading
import time
import eventlet
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template, Response
from flask_socketio import SocketIO, emit

eventlet.monkey_patch()

# KONFIGURACJA 
# Pobieramy zmienne z systemu (Environment Variables) <- na Render!.
# Drugi parametr to wartość domyślna 

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tajny_klucz_lokalny_123')

ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS', 'admin')

DRONE_API_KEY = os.environ.get('DRONE_API_KEY', '12345')

DB_FILE = "drones_state.json"

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')
drones_db = {}
db_lock = threading.Lock()

def load_db():
    """Ładuje stan z pliku przy starcie"""
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
    """Zapisuje stan do pliku co 10 sekund w tle (nie blokuje serwera)"""
    while True:
        time.sleep(10)
        with db_lock:
            try:
                with open(DB_FILE, 'w') as f:
                    json.dump(drones_db, f, indent=4)
            except Exception as e:
                print(f"[ERROR] Błąd zapisu tła: {e}")

# Start wątku zapisującego
saver_thread = threading.Thread(target=save_db_background, daemon=True)
saver_thread.start()

def get_drone_entry(drone_id):
    """Tworzy lub pobiera wpis drona. Nowe drony są domyślnie 'nieśledzone'."""
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
    """Wysyła stan wszystkich dronów do przeglądarki przez WebSocket"""
    all_drones_snapshot = []
    with db_lock:
        for d_id, d_data in drones_db.items():
            # Wysyłamy tylko jeśli mamy jakiekolwiek dane telemetryczne
            if d_data.get("telemetry"):
                telem_copy = d_data["telemetry"].copy()
                telem_copy["server_assigned_role"] = d_data.get("assigned_role", "None")
                # Status Online/Offline (timeout 10s)
                telem_copy["online"] = (time.time() - d_data.get("last_seen", 0)) < 10
                telem_copy["is_tracked"] = d_data.get("is_tracked", False)
                all_drones_snapshot.append(telem_copy)
    
    socketio.emit('telemetry_update', all_drones_snapshot)

def check_auth(username, password):
    """Sprawdza login/hasło operatora"""
    return username == ADMIN_USER and password == ADMIN_PASS

def authenticate():
    return Response(
        'Błędne dane logowania.\n', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    """Zabezpiecza widok panelu WWW"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def requires_drone_token(f):
    """Zabezpiecza API dla dronów (sprawdza X-Drone-Token)"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Drone-Token')
        # Jeśli token nie pasuje, odrzuć
        if token != DRONE_API_KEY:
            return jsonify({'error': 'Unauthorized: Invalid Token'}), 401
        return f(*args, **kwargs)
    return decorated

@app.route("/")
@requires_auth
def index():
    return render_template("index.html")

@app.route("/api/telemetry", methods=["POST"])
@requires_drone_token
def receive_telemetry():
    """Dron wysyła tu dane. Serwer zapisuje i wysyła WebSocketem do GUI."""
    data = request.get_json()
    drone_id = data.get("drone_id")
    
    if not drone_id: 
        return jsonify({"error": "No drone_id"}), 400
    
    with db_lock:
        entry = get_drone_entry(drone_id)
        
        # Aktualizacja danych
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
        
        # Odpowiedź dla drona 
        response_payload = {
            "role": entry["assigned_role"],
            "mission": entry["current_mission"]
        }

    # Push do klienta WWW (Real-time)
    push_update_to_clients()

    return jsonify(response_payload), 200

# Te endpointy wywołuje script.js w przeglądarce

@app.route("/api/init_state", methods=["GET"])
@requires_auth
def get_init_state():
    """Zwraca stan początkowy dla WebSocketa przy odświeżeniu strony"""
    push_update_to_clients()
    return jsonify({"status": "ok"})

@app.route("/api/drone/add", methods=["POST"])
@requires_auth
def add_drone():
    data = request.get_json()
    drone_id = data.get("drone_id")
    with db_lock:
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
    with db_lock:
        if drone_id in drones_db:
            drones_db[drone_id]["is_tracked"] = False
            # Czyścimy misję przy odznaczeniu
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
    
    with db_lock:
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
    
    with db_lock:
        # Jeśli lista pusta, zatrzymaj wszystkie
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
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)