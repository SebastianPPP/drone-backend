import eventlet
eventlet.monkey_patch()

import os
import json
import time
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template, Response
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['PROPAGATE_EXCEPTIONS'] = True
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tajny_klucz_lokalny_123')

ADMIN_USER   = os.environ.get('ADMIN_USER',   'admin')
ADMIN_PASS   = os.environ.get('ADMIN_PASS',   'admin')
DRONE_API_KEY = os.environ.get('DRONE_API_KEY', '12345')
DB_FILE = "drones_state.json"

socketio = SocketIO(app,
                    cors_allowed_origins="*",
                    async_mode='eventlet',
                    ping_timeout=10,
                    ping_interval=5)

drones_db = {}

# ─── DB ───────────────────────────────────────────────────────────────────────

def load_db():
    global drones_db
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                drones_db = json.load(f)
            print(f"[SYSTEM] Zaladowano baze: {len(drones_db)} dronow.")
        except Exception as e:
            print(f"[ERROR] Blad odczytu DB: {e}")
            drones_db = {}

def save_db_background():
    while True:
        socketio.sleep(10)
        try:
            with open(DB_FILE, 'w') as f:
                json.dump(drones_db, f, indent=4)
        except Exception as e:
            print(f"[ERROR] Blad zapisu tla: {e}")

def get_drone_entry(drone_id):
    if drone_id not in drones_db:
        drones_db[drone_id] = {
            "telemetry":       {},
            "assigned_role":   "None",
            "current_mission": None,
            "last_seen":       0,
            "is_tracked":      False,
            # Kolejka komend czekajacych na odebranie przez RPi
            "pending_commands": [],
        }
    # Migracja starych wpisow bez pending_commands
    if "pending_commands" not in drones_db[drone_id]:
        drones_db[drone_id]["pending_commands"] = []
    return drones_db[drone_id]

def push_update_to_clients():
    all_drones_snapshot = []
    for d_id in list(drones_db.keys()):
        d_data = drones_db[d_id]
        if d_data.get("telemetry"):
            telem_copy = d_data["telemetry"].copy()

            role = d_data.get("assigned_role", "None")
            telem_copy["server_assigned_role"] = "brak" if role == "None" else role

            mission   = d_data.get("current_mission")
            target_wp = telem_copy.get("target_wp", 0)
            if mission:
                wp_display = "KONIEC" if target_wp == 999 else (str(target_wp) if target_wp > 0 else "-")
                telem_copy["mission_display"] = f"{mission['id']} / {wp_display}"
            else:
                telem_copy["mission_display"] = "brak"

            telem_copy["online"]        = (time.time() - d_data.get("last_seen", 0)) < 15
            telem_copy["is_tracked"]    = d_data.get("is_tracked", False)
            telem_copy["pending_cmds"]  = len(d_data.get("pending_commands", []))
            all_drones_snapshot.append(telem_copy)

    socketio.emit('telemetry_update', all_drones_snapshot)

# ─── AUTH ─────────────────────────────────────────────────────────────────────

def check_auth(username, password):
    return username == ADMIN_USER and password == ADMIN_PASS

def authenticate():
    return Response('Bledne dane logowania.\n', 401,
                    {'WWW-Authenticate': 'Basic realm="Login Required"'})

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

# ─── ENDPOINTY FRONTEND ───────────────────────────────────────────────────────

@app.route("/")
@requires_auth
def index():
    return render_template("index.html")

@app.route("/api/drones", methods=["GET"])
def get_all_drones_public():
    public_list = []
    for d_id, data in drones_db.items():
        if data.get("telemetry"):
            public_list.append(data["telemetry"])
    return jsonify(public_list), 200

@app.route("/api/init_state", methods=["GET"])
@requires_auth
def get_init_state():
    push_update_to_clients()
    return jsonify({"status": "ok"})

@app.route("/api/drone/add", methods=["POST"])
@requires_auth
def add_drone():
    data     = request.get_json()
    drone_id = data.get("drone_id")
    if drone_id in drones_db:
        drones_db[drone_id]["is_tracked"] = True
        push_update_to_clients()
        return jsonify({"status": "ADDED"})
    return jsonify({"error": "Not found"}), 404

@app.route("/api/drone/delete", methods=["POST"])
@requires_auth
def delete_drone():
    data     = request.get_json()
    drone_id = data.get("drone_id")
    if drone_id in drones_db:
        drones_db[drone_id]["is_tracked"]      = False
        drones_db[drone_id]["current_mission"] = None
        drones_db[drone_id]["assigned_role"]   = "None"
        push_update_to_clients()
        return jsonify({"status": "UNTRACKED"})
    return jsonify({"error": "Not found"}), 404

@app.route("/api/mission/upload", methods=["POST"])
@requires_auth
def upload_mission():
    data           = request.get_json()
    drones_payload = data.get("drones", {})
    for drone_id, mission_config in drones_payload.items():
        entry = get_drone_entry(drone_id)
        entry["is_tracked"] = True
        mission_id  = mission_config.get("mission_id", "m_{}".format(int(time.time()*1000)))
        waypoints   = mission_config.get("waypoints", [])
        entry["current_mission"] = {
            "id":        mission_id,
            "waypoints": waypoints,
            "version":   int(time.time() * 1000),
        }
        if "role" in mission_config:
            entry["assigned_role"] = mission_config["role"]
        # Zawsze nadpisz kolejkę - usun stare upload_mission, wstaw nowy
        entry["pending_commands"] = [
            c for c in entry["pending_commands"]
            if c.get("type") != "upload_mission"
        ]
        _enqueue_command(drone_id, {
            "type":       "upload_mission",
            "mission_id": mission_id,
            "waypoints":  waypoints,
            "version":    entry["current_mission"]["version"],
        })
    push_update_to_clients()
    return jsonify({"status": "STORED"})

@app.route("/api/mission/stop", methods=["POST"])
@requires_auth
def stop_mission():
    data          = request.get_json()
    target_drones = data.get("drones", [])
    if not target_drones:
        target_drones = list(drones_db.keys())
    for drone_id in target_drones:
        if drone_id in drones_db:
            drones_db[drone_id]["current_mission"] = None
            drones_db[drone_id]["assigned_role"]   = "None"
            _enqueue_command(drone_id, {"type": "clear_mission"})
    push_update_to_clients()
    return jsonify({"status": "STOPPED"})

# ─── ENDPOINTY KOMEND (nowe) ──────────────────────────────────────────────────

def _enqueue_command(drone_id, cmd):
    """Dodaje komende do kolejki danego drona."""
    entry = get_drone_entry(drone_id)
    cmd["enqueued_at"] = time.time()
    cmd["id"]          = f"{drone_id}_{int(cmd['enqueued_at']*1000)}"
    entry["pending_commands"].append(cmd)
    print(f"[CMD] {drone_id} <- {cmd['type']}")

@app.route("/api/drone/command", methods=["POST"])
@requires_auth
def send_command():
    """
    Endpoint wywoływany przez panel GCS.
    Obsługiwane typy komend:
      arm          - uzbrojenie silnikow
      disarm       - rozbrojenie
      set_mode     - zmiana trybu (param: mode = GUIDED / AUTO / LOITER / RTL / LAND / STABILIZE ...)
      upload_mission - wgranie trasy (param: waypoints = [{lat,lon,alt}, ...])
      clear_mission  - usuniecie misji z FC
    """
    data     = request.get_json()
    drone_id = data.get("drone_id")
    cmd_type = data.get("type")

    if not drone_id or not cmd_type:
        return jsonify({"error": "Brak drone_id lub type"}), 400
    if drone_id not in drones_db:
        return jsonify({"error": "Nieznany dron"}), 404

    allowed = {"arm", "disarm", "set_mode", "upload_mission", "clear_mission"}
    if cmd_type not in allowed:
        return jsonify({"error": f"Nieznana komenda: {cmd_type}"}), 400

    cmd = {"type": cmd_type}
    if cmd_type == "set_mode":
        mode = data.get("mode", "").upper()
        if not mode:
            return jsonify({"error": "Brak parametru mode"}), 400
        cmd["mode"] = mode
    if cmd_type == "upload_mission":
        wps = data.get("waypoints", [])
        if not wps:
            return jsonify({"error": "Brak waypoints"}), 400
        mission_id = data.get("mission_id", "GCS_{}".format(int(time.time()*1000)))
        version    = int(time.time() * 1000)
        cmd["waypoints"]  = wps
        cmd["mission_id"] = mission_id
        cmd["version"]    = version
        # Aktualizuj tez current_mission zeby przetrwalo restart symulatora
        entry = get_drone_entry(drone_id)
        entry["current_mission"] = {
            "id": mission_id, "waypoints": wps, "version": version
        }
        # Nadpisz stare upload_mission w kolejce
        entry["pending_commands"] = [
            c for c in entry["pending_commands"]
            if c.get("type") != "upload_mission"
        ]

    _enqueue_command(drone_id, cmd)
    push_update_to_clients()
    return jsonify({"status": "QUEUED", "cmd": cmd["type"]})

# ─── ENDPOINTY RPi (polling komend) ──────────────────────────────────────────

@app.route("/api/telemetry", methods=["POST"])
@requires_drone_token
def receive_telemetry():
    try:
        data     = request.get_json()
        drone_id = data.get("drone_id")
        if not drone_id:
            return jsonify({"error": "No drone_id"}), 400

        entry = get_drone_entry(drone_id)

        raw_wp = data.get("target_wp", 0)
        try:
            safe_wp = int(raw_wp)
        except Exception:
            safe_wp = 0

        entry["telemetry"] = {
            "drone_id":   drone_id,
            "lat":        data.get("lat"),
            "lon":        data.get("lon"),
            "alt":        data.get("alt", 0),
            "battery":    data.get("battery", 0),
            "roll":       data.get("roll", 0),
            "pitch":      data.get("pitch", 0),
            "yaw":        data.get("yaw", 0),
            "target_wp":  safe_wp,
            "timestamp":  datetime.utcnow().isoformat() + "Z",
            # Pola z RPi
            "armed":      data.get("armed", False),
            "mode":       data.get("mode", "UNKNOWN"),
            "gps_fix":    data.get("gps_fix", 0),
            "satellites": data.get("satellites", 0),
            "groundspeed":data.get("groundspeed", 0),
            "has_camera": data.get("has_camera", False),
            "cam_url":    data.get("cam_url", None),
        }
        entry["last_seen"] = time.time()

        # Zwroc kolejke komend RPi i wyczysc ja
        pending = entry.get("pending_commands", [])
        entry["pending_commands"] = []

        push_update_to_clients()

        return jsonify({
            "role":     entry["assigned_role"],
            "mission":  entry["current_mission"],
            "commands": pending          # <-- RPi odbiera i wykonuje
        }), 200

    except Exception as e:
        print(f"Blad telemetrii: {e}")
        return jsonify({"error": "Internal Error"}), 500

@app.route("/api/command/ack", methods=["POST"])
@requires_drone_token
def command_ack():
    """RPi potwierdza wykonanie komendy."""
    data     = request.get_json()
    drone_id = data.get("drone_id")
    cmd_id   = data.get("cmd_id")
    success  = data.get("success", True)
    msg      = data.get("message", "")
    print(f"[ACK] {drone_id} cmd={cmd_id} ok={success} msg={msg}")
    # Emituj potwierdzenie do panelu
    socketio.emit('cmd_ack', {"drone_id": drone_id, "cmd_id": cmd_id, "success": success, "message": msg})
    return jsonify({"status": "ok"})

# ─── START ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    load_db()
    socketio.start_background_task(save_db_background)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
else:
    load_db()
    socketio.start_background_task(save_db_background)