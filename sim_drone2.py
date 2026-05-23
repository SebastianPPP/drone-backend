"""
sim_leader.py — Symulator lidera z kamera USB
- Wysyla telemetrie do GCS co 0.1s
- Serwuje MJPEG stream z kamery USB na http://localhost:8080/video

Uzycie:
    python3 sim_leader.py
    python3 sim_leader.py --camera-index 0   # indeks kamery (domyslnie 0)
    python3 sim_leader.py --cam-port 8080     # port streamu
"""

import requests
import time
import math
import argparse
import random
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# OpenCV - wymagane tylko dla kamery
try:
    import cv2
    CV2_OK = True
except ImportError:
    CV2_OK = False
    print("[WARN] Brak opencv-python. Zainstaluj: pip3 install opencv-python")

# ─── ARGUMENTY ────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Symulator lidera z kamera")
parser.add_argument("--host",         default="drone-backend-2-1mwz.onrender.com")
parser.add_argument("--id",           default="skimmer1")
parser.add_argument("--token",        default="ZTBdrony")
parser.add_argument("--lat",          default=52.2297, type=float)
parser.add_argument("--lon",          default=21.0122, type=float)
parser.add_argument("--radius",       default=0.0006,  type=float)
parser.add_argument("--alt",          default=30.0,    type=float)
parser.add_argument("--speed",        default=1.0,     type=float)
parser.add_argument("--camera-index", default=0,       type=int,  help="Indeks kamery USB (0, 1, 2...)")
parser.add_argument("--cam-port",     default=8080,    type=int,  help="Port streamu MJPEG")
parser.add_argument("--no-camera",    action="store_true",        help="Wylaczy kamere")
args = parser.parse_args()

BASE_URL = "https://{}".format(args.host)
ENDPOINT = BASE_URL + "/api/telemetry"
HEADERS  = {"Content-Type": "application/json", "X-Drone-Token": args.token}

COLORS = {
    "reset": "\033[0m", "green": "\033[92m", "yellow": "\033[93m",
    "red": "\033[91m",  "cyan":  "\033[96m", "blue":   "\033[94m", "dim": "\033[2m",
}
def c(color, text):
    return COLORS.get(color, "") + str(text) + COLORS["reset"]

# ─── KAMERA / MJPEG SERVER ────────────────────────────────────────────────────
camera    = None
cam_lock  = threading.Lock()
HAS_CAMERA = False

def init_camera():
    global camera, HAS_CAMERA
    if args.no_camera or not CV2_OK:
        return
    cap = cv2.VideoCapture(args.camera_index)
    if not cap.isOpened():
        print(c("yellow", "[CAM] Nie mozna otworzyc kamery index={}. Sprobuj --camera-index 1".format(args.camera_index)))
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 25)
    camera = cap
    HAS_CAMERA = True
    print(c("green", "[CAM] Kamera {} otwarta. Stream: http://localhost:{}/video".format(args.camera_index, args.cam_port)))

def get_frame_jpeg():
    """Zwraca aktualny klatke jako JPEG bytes, lub None."""
    if camera is None:
        return None
    with cam_lock:
        ret, frame = camera.read()
    if not ret:
        return None
    # Nakladka HUD na obraz
    yaw_str = "YAW: {:.1f}".format(current_yaw)
    bat_str = "BAT: {:.1f}%".format(current_bat)
    lat_str = "LAT: {:.5f}".format(current_lat)
    lon_str = "LON: {:.5f}".format(current_lon)
    overlay_color = (0, 255, 80)
    font = cv2.FONT_HERSHEY_SIMPLEX
    # Ramka
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w-1, h-1), overlay_color, 2)
    # Dane telemetryczne
    cv2.putText(frame, args.id,  (10, 24),  font, 0.6, overlay_color, 1)
    cv2.putText(frame, yaw_str,  (10, 46),  font, 0.5, overlay_color, 1)
    cv2.putText(frame, bat_str,  (10, 64),  font, 0.5, overlay_color, 1)
    cv2.putText(frame, lat_str,  (10, h-30),font, 0.45, overlay_color, 1)
    cv2.putText(frame, lon_str,  (10, h-12),font, 0.45, overlay_color, 1)
    # Celownik
    cx, cy = w//2, h//2
    cv2.line(frame, (cx-20, cy), (cx+20, cy), overlay_color, 1)
    cv2.line(frame, (cx, cy-20), (cx, cy+20), overlay_color, 1)
    cv2.circle(frame, (cx, cy), 30, overlay_color, 1)

    _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return buf.tobytes()

class MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *a):
        pass  # wycisz logi HTTP

    def do_GET(self):
        if self.path == "/video":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    frame = get_frame_jpeg()
                    if frame:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.04)  # ~25fps
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"camera": true}' if HAS_CAMERA else b'{"camera": false}')
        else:
            self.send_response(404)
            self.end_headers()

def run_mjpeg_server():
    server = HTTPServer(("0.0.0.0", args.cam_port), MJPEGHandler)
    server.serve_forever()

# ─── TELEMETRIA (stan globalny dla HUD na klatce) ─────────────────────────────
current_yaw = 0.0
current_bat = 100.0
current_lat = args.lat
current_lon = args.lon

# ─── MAIN ─────────────────────────────────────────────────────────────────────
print(c("blue", """
+------------------------------------------+
|    GCS LEADER + CAMERA // sim_leader.py  |
+------------------------------------------+"""))
print(c("blue", "  ID     : " + args.id))
print(c("blue", "  Server : " + BASE_URL))

init_camera()

if HAS_CAMERA:
    t = threading.Thread(target=run_mjpeg_server, daemon=True)
    t.start()
    print(c("green", "  Stream : http://localhost:{}/video".format(args.cam_port)))
else:
    print(c("yellow", "  Stream : BRAK KAMERY"))

print(c("blue", "+------------------------------------------+\n"))
print(c("dim", "Ctrl+C aby zatrzymac\n"))

battery = 100.0
angle   = 0.0
tick    = 0
errors  = 0

while True:
    tick  += 1
    angle += 0.025 * args.speed

    lat = args.lat + math.sin(angle) * args.radius
    lon = args.lon + math.cos(angle) * args.radius
    yaw = (math.degrees(angle + math.pi / 2)) % 360
    alt = args.alt + math.sin(angle * 0.7) * 2 + random.uniform(-0.3, 0.3)
    roll  = math.sin(angle * 2) * 6 + random.uniform(-1, 1)
    pitch = math.cos(angle * 3) * 4 + random.uniform(-1, 1)
    battery -= random.uniform(0.005, 0.02)
    battery  = max(0.0, battery)

    # Aktualizuj globalny stan dla HUD na obrazie
    current_yaw = yaw
    current_bat = battery
    current_lat = lat
    current_lon = lon

    bat_color = "green" if battery > 40 else ("yellow" if battery > 20 else "red")

    payload = {
        "drone_id":   args.id,
        "lat":        round(lat, 7),
        "lon":        round(lon, 7),
        "alt":        round(alt, 1),
        "battery":    round(battery, 1),
        "roll":       round(roll, 2),
        "pitch":      round(pitch, 2),
        "yaw":        round(yaw, 1),
        "target_wp":  0,
        "has_camera": HAS_CAMERA,
        "cam_url":    "http://localhost:{}/video".format(args.cam_port) if HAS_CAMERA else None,
    }

    try:
        resp = requests.post(ENDPOINT, json=payload, headers=HEADERS, timeout=3)

        if resp.status_code == 200:
            errors = 0
            lat_s = "{:.5f}".format(lat)
            lon_s = "{:.5f}".format(lon)
            cam_s = c("green", "CAM:ON") if HAS_CAMERA else c("dim", "CAM:OFF")
            print(
                c("dim",  "[{:>4}]".format(tick)) + " " +
                c("blue", "LEADER " + args.id) +
                c("dim",  "  |  ") +
                "LAT " + c("cyan", lat_s) + "  " +
                "LON " + c("cyan", lon_s) + "  " +
                "YAW " + c("dim", "{:>5.1f}deg".format(yaw)) + "  " +
                "BAT " + c(bat_color, "{:>5.1f}%".format(battery)) + "  " +
                cam_s
            )
        elif resp.status_code == 401:
            print(c("red", "[BLAD 401] Zly token!"))
            sys.exit(1)
        else:
            print(c("red", "[BLAD {}]".format(resp.status_code)))
            errors += 1

    except requests.exceptions.ConnectionError:
        errors += 1
        print(c("red", "[BRAK POLACZENIA] proba {}...".format(errors)))
        if errors >= 10:
            sys.exit(1)
    except requests.exceptions.Timeout:
        print(c("yellow", "[TIMEOUT]"))
        errors += 1
    except KeyboardInterrupt:
        print(c("blue", "\nZATRZYMANO po {} tickach.".format(tick)))
        if camera:
            camera.release()
        sys.exit(0)

    time.sleep(0.1)