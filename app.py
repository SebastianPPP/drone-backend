from flask import Flask, request, jsonify, render_template
from datetime import datetime

app = Flask(__name__)

latest_data = {}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/telemetry", methods=["POST"])
def receive_telemetry():
    data = request.json
    drone_id = data.get("drone_id")
    if not drone_id:
        return jsonify({"error": "Missing drone_id"}), 400

    data["timestamp"] = datetime.utcnow().isoformat()
    latest_data[drone_id] = data
    return jsonify({"message": "Telemetry received"}), 200

@app.route("/api/telemetry/latest/<drone_id>", methods=["GET"])
def get_telemetry(drone_id):
    data = latest_data.get(drone_id)
    if not data:
        return jsonify({"error": "Drone not found"}), 404
    return jsonify(data)

@app.route("/api/telemetry/latest", methods=["GET"])
def get_all_latest_telemetry():
    return jsonify(list(latest_data.values()))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
