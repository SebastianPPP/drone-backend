from flask import Flask, request, jsonify
from datetime import datetime
import time
from flask import render_template

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

# Dane w pamięci (na czas działania serwera)
telemetry_by_drone = {}  # drone_id -> telemetry dict
mission_by_drone = {}    # drone_id -> assigned mission
status_by_drone = {}     # drone_id -> mission status

@app.route("/api/mission/upload", methods=["POST"])
def upload_mission():
    data = request.get_json()
    drones = data.get("drones", [])

    if not drones:
        return jsonify({"error": "Brak danych misji"}), 400

    # Sprawdź które drony są aktywne (czy mają aktualną telemetrię)
    active_drones = {
        drone_id for drone_id, t in telemetry_by_drone.items()
        if time.time() - t.get("timestamp_unix", 0) < 15
    }

    requested_drones = {d["droneId"] for d in drones}
    missing_drones = requested_drones - active_drones

    if missing_drones:
        return jsonify({
            "status": "error",
            "message": "Niektóre drony są nieaktywne",
            "missing": list(missing_drones)
        }), 400

    # Zapisz misje dla każdego drona
    for d in drones:
        drone_id = d["droneId"]
        mission_by_drone[drone_id] = d["path"]
        status_by_drone[drone_id] = "assigned"

    return jsonify({"status": "ok", "assigned": list(requested_drones)})

@app.route("/api/mission/status", methods=["POST"])
def mission_status_update():
    data = request.get_json()
    drone_id = data.get("droneId")
    status = data.get("status")

    if not drone_id or not status:
        return jsonify({"error": "Brakuje droneId lub status"}), 400

    status_by_drone[drone_id] = status
    return jsonify({"status": "updated"}), 200

@app.route("/api/telemetry", methods=["GET", "POST"])
def telemetry():
    global telemetry_by_drone

    if request.method == "POST":
        data = request.get_json()
        drone_id = data.get("drone_id")
        lat = data.get("lat")
        lon = data.get("lon")
        battery = data.get("battery")  # <--- NOWE
        alt = data.get("alt")
        
        if not drone_id or lat is None or lon is None:
            return jsonify({"error": "Brak danych telemetrycznych"}), 400

        telemetry_by_drone[drone_id] = {
            "drone_id": drone_id,
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "battery": battery,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "timestamp_unix": time.time()
        }
        return jsonify({"status": "telemetry received"}), 200

    # GET – zwraca wszystkie aktywne dane
    return jsonify(list(telemetry_by_drone.values()))

if __name__ == "__main__":
    app.run(debug=True)
