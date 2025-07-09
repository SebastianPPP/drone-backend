from flask import Flask, request, jsonify
import sqlite3
import time
import os

app = Flask(__name__)
DB_NAME = 'telemetry.db'

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                drone_id TEXT NOT NULL,
                timestamp REAL,
                lat REAL,
                lon REAL,
                alt REAL
            )
        ''')

@app.route('/api/telemetry', methods=['POST'])
def receive_telemetry():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Brak danych JSON"}), 400

    drone_id = data.get('drone_id')
    gps = data.get('gps')
    if not drone_id or not gps:
        return jsonify({"error": "Brak drone_id lub gps"}), 400

    timestamp = data.get('timestamp', time.time())
    lat = gps.get('lat')
    lon = gps.get('lon')
    alt = gps.get('alt')

    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            'INSERT INTO telemetry (drone_id, timestamp, lat, lon, alt) VALUES (?, ?, ?, ?, ?)',
            (drone_id, timestamp, lat, lon, alt)
        )
    return jsonify({"status": "ok"}), 200

@app.route('/api/telemetry/latest/<drone_id>', methods=['GET'])
def get_latest_for_drone(drone_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            'SELECT timestamp, lat, lon, alt FROM telemetry WHERE drone_id = ? ORDER BY timestamp DESC LIMIT 1',
            (drone_id,)
        )
        row = cursor.fetchone()
        if row:
            return jsonify({
                "timestamp": row[0],
                "lat": row[1],
                "lon": row[2],
                "alt": row[3]
            })
        else:
            return jsonify({"error": "Brak danych dla tego drona"}), 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

