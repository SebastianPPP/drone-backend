"""
sim_leader.py — Symulator drona z fizyką + misją + kamera USB
"""

import requests, time, math, argparse, random, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    import cv2
    CV2_OK = True
except ImportError:
    CV2_OK = False

# ─── ARGUMENTY ────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--host",         default="drone-backend-2-1mwz.onrender.com")
parser.add_argument("--id",           default="skimmer1")
parser.add_argument("--token",        default="ZTBdrony")
parser.add_argument("--lat",          default=52.2297,  type=float)
parser.add_argument("--lon",          default=21.0122,  type=float)
parser.add_argument("--alt",          default=30.0,     type=float)
parser.add_argument("--speed",        default=1.0,      type=float)
parser.add_argument("--wp-radius",    default=4.0,      type=float, help="Promien akceptacji WP [m]")
parser.add_argument("--cruise-speed", default=8.0,      type=float, help="Predkosc przelotowa [m/s]")
parser.add_argument("--no-orbit",     action="store_true")
parser.add_argument("--camera-index", default=0,        type=int)
parser.add_argument("--cam-port",     default=8080,     type=int)
parser.add_argument("--cam-host",     default=None,     help="Publiczne IP/hostname tego komputera (np. 192.168.1.10). Domyslnie: auto-wykrycie.")
parser.add_argument("--no-camera",    action="store_true")
args = parser.parse_args()

BASE_URL = "https://{}".format(args.host)
ENDPOINT = BASE_URL + "/api/telemetry"
HEADERS  = {"Content-Type": "application/json", "X-Drone-Token": args.token}
DT       = 0.1
R_EARTH  = 6371000.0

C = {"r":"\033[0m","g":"\033[92m","y":"\033[93m","e":"\033[91m",
     "c":"\033[96m","b":"\033[94m","d":"\033[2m","m":"\033[95m","w":"\033[1m"}
def c(col, t): return C.get(col,"") + str(t) + C["r"]
def log(tag, msg, col="d"): print(c(col,"[{}]".format(tag)) + " " + str(msg), flush=True)

# ─── GPS <-> METRY ────────────────────────────────────────────────────────────

def gps_to_m(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * (math.pi/180) * R_EARTH
    dx = (lon2 - lon1) * (math.pi/180) * R_EARTH * math.cos(math.radians((lat1+lat2)/2))
    return dx, dy

def m_to_gps(lat0, lon0, dx, dy):
    lat = lat0 + (dy / R_EARTH) * (180/math.pi)
    lon = lon0 + (dx / (R_EARTH * math.cos(math.radians(lat0)))) * (180/math.pi)
    return lat, lon

def dist_m(lat1, lon1, lat2, lon2):
    return math.hypot(*gps_to_m(lat1, lon1, lat2, lon2))

# ─── FIZYKA ───────────────────────────────────────────────────────────────────

class Drone:
    def __init__(self, lat, lon, alt):
        self.lat = lat; self.lon = lon; self.alt = alt
        self.vx = 0.0;  self.vy = 0.0
        self.yaw = 0.0; self.yaw_rate = 0.0
        self.yaw_err_i = 0.0
        self.mass = 2.0; self.drag = 0.4
        self.max_force = 60.0; self.max_yaw_torque = 15.0

    def _yaw_pid(self, target_rad, dt):
        err = math.atan2(math.sin(target_rad - self.yaw), math.cos(target_rad - self.yaw))
        self.yaw_err_i = max(-1.0, min(1.0, self.yaw_err_i + err * dt))
        t = 8.0*err + 2.0*self.yaw_err_i - 1.5*self.yaw_rate
        return max(-self.max_yaw_torque, min(self.max_yaw_torque, t))

    def step_to(self, tlat, tlon, dt, spd=8.0):
        dx, dy = gps_to_m(self.lat, self.lon, tlat, tlon)
        dist = math.hypot(dx, dy)
        if dist < 0.05:
            self.vx *= 0.6; self.vy *= 0.6
            self._integrate(0, 0, dt); return

        v_des = min(spd * args.speed, dist * 2.0)
        ux = dx/dist * v_des; uy = dy/dist * v_des
        fx = (ux - self.vx) * self.mass * 3.5
        fy = (uy - self.vy) * self.mass * 3.5
        nm = math.hypot(fx, fy)
        if nm > self.max_force: fx=fx/nm*self.max_force; fy=fy/nm*self.max_force

        ty = self._yaw_pid(math.atan2(dy, dx), dt)
        self.yaw_rate += (ty - 3.0*self.yaw_rate) * dt
        self.yaw = math.atan2(math.sin(self.yaw + self.yaw_rate*dt),
                              math.cos(self.yaw + self.yaw_rate*dt))
        self._integrate(fx, fy, dt)

    def step_hover(self, dt):
        self.vx *= max(0, 1-self.drag*dt*4)
        self.vy *= max(0, 1-self.drag*dt*4)
        self.yaw_rate *= 0.7
        self._integrate(0, 0, dt)

    def _integrate(self, fx, fy, dt):
        self.vx += (fx - self.drag*self.vx)/self.mass * dt
        self.vy += (fy - self.drag*self.vy)/self.mass * dt
        self.lat, self.lon = m_to_gps(self.lat, self.lon, self.vx*dt, self.vy*dt)

    @property
    def speed(self): return math.hypot(self.vx, self.vy)
    @property
    def yaw_deg(self): return math.degrees(self.yaw) % 360
    @property
    def roll_sim(self): return max(-25,min(25,-math.degrees(self.yaw_rate)*1.8))
    @property
    def pitch_sim(self):
        fwd = self.vx*math.cos(self.yaw)+self.vy*math.sin(self.yaw)
        return max(-20,min(20,fwd*1.5))

# ─── PARSOWANIE WAYPOINTÓW ───────────────────────────────────────────────────

def parse_waypoints(raw):
    if not raw:
        return []
    result = []
    for i, wp in enumerate(raw):
        try:
            if isinstance(wp, (list, tuple)):
                lat = float(wp[0])
                lon = float(wp[1])
                alt = float(wp[2]) if len(wp) > 2 else args.alt
            elif isinstance(wp, dict):
                lat = float(wp.get("lat", wp.get("latitude", 0)))
                lon = float(wp.get("lon", wp.get("lng", wp.get("longitude", 0))))
                alt = float(wp.get("alt", wp.get("altitude", args.alt)))
            else:
                log("WP","Nieznany format WP[{}]: {}".format(i, repr(wp)),"y")
                continue

            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                log("WP","WP[{}] poza zakresem: lat={} lon={}".format(i,lat,lon),"e")
                continue
            if lat == 0.0 and lon == 0.0:
                continue

            result.append({"lat": lat, "lon": lon, "alt": alt})
        except Exception as ex:
            log("WP","Blad parsowania WP[{}]: {} -> {}".format(i, repr(wp), ex),"e")

    return result

# ─── KAMERA ──────────────────────────────────────────────────────────────────

camera     = None
cam_lock   = threading.Lock()
HAS_CAMERA = False
hud_ref    = {}

def init_camera():
    global camera, HAS_CAMERA
    if args.no_camera or not CV2_OK:
        return
    for idx in ([args.camera_index] + ([0,1,2] if args.camera_index != 0 else [1,2])):
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)  # Odchudzony strumień
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240) # Odchudzony strumień
            cap.set(cv2.CAP_PROP_FPS, 15)           # Odchudzony strumień
            camera = cap
            HAS_CAMERA = True
            log("CAM","Kamera index={} otwarta. Stream: http://localhost:{}/video".format(idx, args.cam_port),"g")
            return
        cap.release()
    log("CAM","Nie znaleziono zadnej kamery USB. Sprobuj --camera-index 1","y")

def get_frame_jpeg():
    if not camera: return None
    with cam_lock:
        ret, frame = camera.read()
    if not ret: return None
    s  = hud_ref
    oc = (0, 255, 80)
    fn = cv2.FONT_HERSHEY_SIMPLEX
    h, w = frame.shape[:2]

    cv2.rectangle(frame,(0,0),(w-1,h-1),oc,2)
    mode = s.get("mode","—")
    cv2.putText(frame,"{} // {}".format(args.id,mode),(10,22),fn,0.55,oc,1)

    if s.get("wp_total",0) > 0:
        cv2.putText(frame,"WP {}/{}  {:.0f}m".format(
            s.get("wp_idx",0)+1, s.get("wp_total",0), s.get("dist_to_wp",0)),
            (10,40),fn,0.48,oc,1)

    cv2.putText(frame,"SPD {:.1f}m/s  ALT {:.0f}m".format(s.get("speed",0),s.get("alt",0)),(10,57),fn,0.48,oc,1)
    cv2.putText(frame,"BAT {:.0f}%  YAW {:.0f}deg".format(s.get("battery",0),s.get("yaw",0)),(10,74),fn,0.48,oc,1)
    cv2.putText(frame,"{:.5f}, {:.5f}".format(s.get("lat",0),s.get("lon",0)),(10,h-10),fn,0.4,oc,1)

    cx,cy = w//2,h//2
    cv2.line(frame,(cx-20,cy),(cx+20,cy),oc,1)
    cv2.line(frame,(cx,cy-20),(cx,cy+20),oc,1)
    cv2.circle(frame,(cx,cy),32,oc,1)

    bw = int((w-20) * s.get("battery",100)/100)
    bat_col = (0,255,80) if s.get("battery",100)>40 else ((0,200,255) if s.get("battery",100)>20 else (0,0,255))
    cv2.rectangle(frame,(10,h-30),(10+bw,h-22),bat_col,-1)
    cv2.rectangle(frame,(10,h-30),(w-10,h-22),oc,1)

    # Mocniejsza kompresja, żeby nie lagowało w przeglądarce
    _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
    return buf.tobytes()

class MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path == "/video":
            self.send_response(200)
            self.send_header("Content-Type","multipart/x-mixed-replace; boundary=frame")
            self.send_header("Access-Control-Allow-Origin","*")
            self.end_headers()
            try:
                while True:
                    f = get_frame_jpeg()
                    if f:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"+f+b"\r\n")
                    time.sleep(0.04)
            except (BrokenPipeError,ConnectionResetError,OSError): pass
        else:
            self.send_response(404); self.end_headers()

# ─── STARTUP ─────────────────────────────────────────────────────────────────

print(c("b","""
+------------------------------------------+
|   GCS DRONE SIM + MISSION // sim_leader  |
+------------------------------------------+"""))
print(c("b","  ID     : " + args.id))
print(c("b","  Server : " + BASE_URL))
print(c("b","  WP r.  : {:.1f}m  Speed: {}x  Cruise: {}m/s".format(
    args.wp_radius, args.speed, args.cruise_speed)))

def detect_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

CAM_HOST = args.cam_host or detect_local_ip()
CAM_URL  = "http://{}:{}/video".format(CAM_HOST, args.cam_port)

init_camera()
if HAS_CAMERA:
    threading.Thread(
        target=lambda: HTTPServer(("0.0.0.0",args.cam_port),MJPEGHandler).serve_forever(),
        daemon=True).start()
    print(c("g","  Stream : {}".format(CAM_URL)))
else:
    print(c("d","  Stream : brak kamery"))

print(c("b","+------------------------------------------+\n"))

# ─── STAN ─────────────────────────────────────────────────────────────────────

drone        = Drone(args.lat, args.lon, args.alt)
battery      = 100.0
tick         = 0
errors       = 0
orbit_angle  = 0.0
ORBIT_R_DEG  = 0.0006

flight_mode     = "IDLE" if args.no_orbit else "ORBIT"
mission_wps     = []
wp_idx          = 0

# ─── ŁADOWANIE MISJI (helper) ────────────────────────────────────────────────

def _load_mission(cmd):
    global mission_wps, wp_idx, flight_mode

    raw = cmd.get("waypoints")
    if not raw and "drones" in cmd:
        raw = cmd["drones"].get(args.id)
    if not raw and isinstance(cmd, dict):
        raw = cmd.get(args.id)

    if not raw:
        return 

    raw_str = str(raw)
    if getattr(_load_mission, "last_raw", None) == raw_str:
        return 

    parsed = parse_waypoints(raw)
    if not parsed:
        log("MSN", "Blad parsowania misji. Brak obslugiwanych WP.", "e")
        return

    _load_mission.last_raw = raw_str

    was_on_mission = flight_mode in ("MISSION",)
    if was_on_mission and mission_wps and wp_idx < len(parsed):
        pass # Trzyma ten sam WP
    else:
        wp_idx = 0

    mission_wps = parsed
    flight_mode = "MISSION"

    log("MSN", "Zaladowano {} WP (start=WP{})".format(len(mission_wps), wp_idx+1), "g")
    
    # MAGICZNY TELEPORT
    d_start = dist_m(drone.lat, drone.lon, mission_wps[wp_idx]["lat"], mission_wps[wp_idx]["lon"])
    if d_start > 1500:
        log("MSN", "Obszar misji oddalony o {:.1f} km! Teleportuje drona...".format(d_start/1000), "m")
        drone.lat, drone.lon = m_to_gps(mission_wps[wp_idx]["lat"], mission_wps[wp_idx]["lon"], 50, 50)


# ─── GŁÓWNA PĘTLA ─────────────────────────────────────────────────────────────

while True:
    tick += 1
    wp_display   = 0
    dist_to_wp   = 0.0

    # ── Fizyka ────────────────────────────────────────────────────────────────
    if flight_mode == "ORBIT":
        orbit_angle += 0.025 * args.speed
        t_lat = args.lat + math.sin(orbit_angle) * ORBIT_R_DEG
        t_lon = args.lon + math.cos(orbit_angle) * ORBIT_R_DEG
        drone.step_to(t_lat, t_lon, DT, spd=6.0)

    elif flight_mode == "MISSION":
        if not mission_wps:
            flight_mode = "IDLE"; log("MSN","Brak WP — IDLE","y")
        else:
            wp          = mission_wps[wp_idx]
            dist_to_wp  = dist_m(drone.lat, drone.lon, wp["lat"], wp["lon"])
            wp_display  = wp_idx + 1
            drone.step_to(wp["lat"], wp["lon"], DT, spd=args.cruise_speed)

            if dist_to_wp < args.wp_radius:
                log("MSN","WP {} osiagniety ({:.1f}m)".format(wp_idx+1, dist_to_wp),"g")
                wp_idx += 1
                if wp_idx >= len(mission_wps):
                    log("MSN","Misja zakonczona! Wracam do bazy...","g")
                    flight_mode = "RTH"
                    wp_display  = 999

    elif flight_mode == "RTH":
        dist_home  = dist_m(drone.lat, drone.lon, args.lat, args.lon)
        wp_display = 999
        drone.step_to(args.lat, args.lon, DT, spd=args.cruise_speed * 0.7)
        if dist_home < args.wp_radius:
            log("RTH","Powrot do bazy.","g")
            flight_mode = "IDLE" if args.no_orbit else "ORBIT"
            orbit_angle = 0.0

    else:  # IDLE
        drone.step_hover(DT)

    battery -= random.uniform(0.002, 0.006)
    battery  = max(0.0, battery)

    # ── HUD kamery ────────────────────────────────────────────────────────────
    hud_ref.update({
        "lat": drone.lat, "lon": drone.lon, "yaw": drone.yaw_deg,
        "alt": drone.alt, "battery": battery, "speed": drone.speed,
        "mode": flight_mode, "wp_idx": wp_idx,
        "wp_total": len(mission_wps) if flight_mode=="MISSION" else 0,
        "dist_to_wp": dist_to_wp,
    })

    bat_color = "g" if battery>40 else ("y" if battery>20 else "e")
    mission_status_str = "W trakcie" if flight_mode == "MISSION" else ("Zakończona" if flight_mode == "RTH" else "Brak misji")

    # ── Telemetria → serwer ───────────────────────────────────────────────────
    payload = {
        "drone_id":       args.id,
        "lat":            round(drone.lat, 7),
        "lon":            round(drone.lon, 7),
        "alt":            round(drone.alt + random.uniform(-0.1,0.1), 1),
        "battery":        round(battery, 1),
        "roll":           round(drone.roll_sim, 2),
        "pitch":          round(drone.pitch_sim, 2),
        "yaw":            round(drone.yaw_deg, 1),
        "groundspeed":    round(drone.speed, 2),
        "armed":          flight_mode not in ("IDLE",),
        "mode":           flight_mode,
        "mission_status": mission_status_str,
        "gps_fix":        3,
        "satellites":     14,
        "target_wp":      wp_display,
        "has_camera":     HAS_CAMERA,
        "cam_url":        CAM_URL if HAS_CAMERA else None,
    }

    try:
        resp = requests.post(ENDPOINT, json=payload, headers=HEADERS, timeout=3)

        if resp.status_code == 200:
            errors = 0
            data   = resp.json()
            commands = data.get("commands", [])

            for cmd in commands:
                ctype = cmd.get("type","")
                if ctype == "upload_mission":
                    _load_mission(cmd)
                elif ctype == "clear_mission":
                    mission_wps = []; wp_idx = 0;
                    flight_mode = "IDLE" if args.no_orbit else "ORBIT"
                    orbit_angle = 0.0
                    log("CMD","Misja usunieta -> {}".format(flight_mode),"y")
                elif ctype == "arm":
                    if flight_mode == "IDLE": flight_mode = "ORBIT" if not args.no_orbit else "IDLE"
                elif ctype == "disarm":
                    flight_mode = "IDLE"; mission_wps = []; wp_idx = 0
                elif ctype == "set_mode":
                    mode = cmd.get("mode","").upper()
                    if   mode == "AUTO"  and mission_wps: flight_mode = "MISSION"; wp_idx = 0
                    elif mode == "RTL":   flight_mode = "RTH"
                    elif mode in ("LOITER","STABILIZE","POSHOLD","BRAKE","ALT_HOLD"): flight_mode = "IDLE"
                    elif mode == "GUIDED": flight_mode = "ORBIT"

            srv_mission = data.get("mission")
            if srv_mission:
                _load_mission(srv_mission)

            mc = {"MISSION":"g","ORBIT":"c","RTH":"m","IDLE":"d"}.get(flight_mode,"d")
            wp_info = ""
            if flight_mode == "MISSION" and mission_wps:
                wp_info = " WP{}/{} {:.0f}m".format(min(wp_idx+1, len(mission_wps)), len(mission_wps), dist_to_wp)

            print(
                c("d","[{:>5}]".format(tick)) + " " +
                c(mc,"{:<8}".format(flight_mode)) + c("d"," | ") +
                "LAT " + c("c","{:.5f}".format(drone.lat)) + " " +
                "LON " + c("c","{:.5f}".format(drone.lon)) + " " +
                "SPD " + c("d","{:.1f}m/s".format(drone.speed)) + "  " +
                "BAT " + c(bat_color,"{:.1f}%".format(battery)) +
                c("g",wp_info), flush=True
            )

        elif resp.status_code == 401:
            log("HTTP","401 Zly token!","e"); sys.exit(1)
        else:
            errors += 1

    # Tarcza na błędy:
    except requests.exceptions.ConnectionError:
        errors += 1
        log("NET", "Brak polaczenia z serwerem (błąd nr {}). Próbuję dalej...".format(errors), "e")
    except requests.exceptions.Timeout:
        errors += 1
        log("NET", "Serwer nie odpowiada (Timeout). Próbuję dalej...", "y")
    except KeyboardInterrupt:
        if camera: camera.release()
        log("SYS", "Zatrzymano ręcznie (Ctrl+C).", "b")
        sys.exit(0)
    except Exception as e:
        log("ERR", "Niespodziewany błąd programu: {}".format(e), "e")
        time.sleep(1) 

    time.sleep(DT)