import requests
import time
import math
import numpy as np

# --- CONFIG ---
BACKEND_URL = "https://drone-backend-2-1mwz.onrender.com/api/telemetry"
DRONE_ID = "sim_drone_1"
START_LAT = 52.1000
START_LON = 19.3000

# Klasa pomocnicza do przeliczania GPS <-> Metry (Local Frame)
class LocalFrame:
    def __init__(self, lat0, lon0):
        self.lat0 = lat0
        self.lon0 = lon0
        self.R = 6371000 # Promień ziemi

    def gps_to_xy(self, lat, lon):
        x = (lon - self.lon0) * (np.pi/180) * self.R * np.cos(self.lat0 * np.pi/180)
        y = (lat - self.lat0) * (np.pi/180) * self.R
        return x, y

    def xy_to_gps(self, x, y):
        lat = self.lat0 + (y / self.R) * (180/np.pi)
        lon = self.lon0 + (x / (self.R * np.cos(self.lat0 * np.pi/180))) * (180/np.pi)
        return lat, lon

# --- LOGIKA Z PLIKU fuzzyController.py (Dostosowana do klasy) ---
class AdaptiveFuzzyController:
    def __init__(self):
        self.K_PSI = 1.5
        self.K_Z = 15.0
        self.ETA = 5.0
        self.num_rules = 11
        self.centers = np.linspace(-2.0, 2.0, self.num_rules)
        self.width = 2.0
        self.theta = np.zeros(self.num_rules)

    def _fuzzy_basis(self, error_val):
        basis = np.exp(-(error_val - self.centers) ** 2 / (self.width ** 2))
        norm = np.sum(basis)
        return basis / norm if norm > 0 else basis

    def compute(self, state, target_wp, dt=0.05):
        x, y = state['x'], state['y']
        psi = state['yaw']
        r = state['r']
        u = state['u']
        tx, ty = target_wp

        # Line-of-Sight
        desired_psi = math.atan2(ty - y, tx - x)
        e_psi = desired_psi - psi
        e_psi = math.atan2(math.sin(e_psi), math.cos(e_psi))

        # Kinematyka
        alpha_r = self.K_PSI * e_psi
        z_r = r - alpha_r

        # Fuzzy Learning
        xi = self._fuzzy_basis(z_r)
        d_theta = self.ETA * z_r * xi * dt
        self.theta += d_theta
        if np.linalg.norm(self.theta) > 50.0:
            self.theta *= 50.0 / np.linalg.norm(self.theta)

        fuzzy_comp = np.dot(self.theta, xi)
        torque_z = -self.K_Z * z_r - fuzzy_comp
        
        MAX_TORQUE = 40.0
        torque_z = max(min(torque_z, MAX_TORQUE), -MAX_TORQUE)

        # Regulator prędkości (Surge)
        target_speed = 2.0 if abs(e_psi) < 0.5 else 0.5 # Trochę szybciej niż w oryginale
        force_x = 80.0 * (target_speed - u)
        force_x = max(0.0, min(80.0, force_x))

        return force_x, torque_z

# --- FIZYKA SYMULOWANA ---
class PhysicsModel:
    def __init__(self):
        self.u = 0.0 # Prędkość liniowa
        self.r = 0.0 # Prędkość kątowa
        self.m = 20.0 # Masa (kg)
        self.I = 5.0  # Bezwładność
        self.drag_u = 2.0 # Opór wody liniowy
        self.drag_r = 2.0 # Opór wody kątowy

    def step(self, fx, tz, dt):
        # Proste równania ruchu F=ma
        acc_u = (fx - self.drag_u * self.u) / self.m
        acc_r = (tz - self.drag_r * self.r) / self.I
        
        self.u += acc_u * dt
        self.r += acc_r * dt
        return self.u, self.r

# --- MAIN ---
def main():
    geo = LocalFrame(START_LAT, START_LON)
    logic = AdaptiveFuzzyController()
    physics = PhysicsModel()

    # Stan lokalny (x, y w metrach)
    local_x, local_y = 0.0, 0.0
    yaw = 0.0
    
    # Stan globalny
    current_data = {
        "lat": START_LAT, "lon": START_LON, "alt": 10.0, "battery": 100,
        "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
        "role": "None", "mission_id": None, "mission_status": "nothing",
        "current_wp_index": 0
    }
    
    full_mission_path_xy = [] # Waypointy w metrach
    full_mission_path_gps = [] # Oryginalne
    
    dt = 0.1 # Krok symulacji 10Hz

    print(f"--- Start Symulatora LEADER ({DRONE_ID}) ---", flush=True)

    while True:
        # 1. Pobieranie celu (Local Frame)
        target_xy = None
        if current_data["mission_status"] == "active" and full_mission_path_xy:
             target_xy = full_mission_path_xy[current_data["current_wp_index"]]

        # 2. Obliczenia sterownika (Fuzzy Controller)
        fx, tz = 0.0, 0.0
        dist_to_wp = 9999
        
        if target_xy:
            state = {'x': local_x, 'y': local_y, 'yaw': yaw, 'r': physics.r, 'u': physics.u}
            fx, tz = logic.compute(state, target_xy, dt)
            
            dist_to_wp = math.hypot(target_xy[0] - local_x, target_xy[1] - local_y)
            if dist_to_wp < 2.0: # STOP_DIST
                print(f"🎯 Zaliczo WP #{current_data['current_wp_index']}", flush=True)
                current_data["current_wp_index"] += 1
                if current_data["current_wp_index"] >= len(full_mission_path_xy):
                    current_data["mission_status"] = "done"

        # 3. Fizyka
        physics.step(fx, tz, dt)
        
        # Aktualizacja pozycji
        local_x += physics.u * math.cos(yaw) * dt
        local_y += physics.u * math.sin(yaw) * dt
        yaw += physics.r * dt
        
        # Normalizacja kąta
        yaw = math.atan2(math.sin(yaw), math.cos(yaw))

        # Konwersja do GPS
        new_lat, new_lon = geo.xy_to_gps(local_x, local_y)
        current_data["lat"] = new_lat
        current_data["lon"] = new_lon
        current_data["yaw"] = math.degrees(yaw)
        current_data["battery"] -= 0.01

        # 4. Wysyłka Telemetrii
        # Przygotowanie listy następnych punktów (do wizualizacji)
        next_wps_gps = []
        if current_data["mission_status"] == "active":
            idx = current_data["current_wp_index"]
            next_wps_gps = full_mission_path_gps[idx : idx + 5]

        payload = {
            "drone_id": DRONE_ID,
            "lat": current_data["lat"], "lon": current_data["lon"], "alt": 10,
            "battery": round(current_data["battery"], 1),
            "roll": 0, "pitch": 0, "yaw": round(math.degrees(yaw), 2),
            "role": current_data["role"],
            "mission_status": (current_data["mission_status"], current_data["mission_id"]),
            "next_waypoints": next_wps_gps
        }

        try:
            resp = requests.post(BACKEND_URL, json=payload, timeout=1)
            if resp.status_code == 200:
                data = resp.json()
                if "role" in data: current_data["role"] = data["role"]
                
                # Pobranie nowej misji
                if "mission" in data and data["mission"]:
                    new_msn = data["mission"]
                    if new_msn.get("id") != current_data["mission_id"]:
                        print(f"📜 Nowa misja: {new_msn.get('id')}", flush=True)
                        current_data["mission_id"] = new_msn.get("id")
                        full_mission_path_gps = new_msn.get("waypoints")
                        
                        # Przeliczenie Waypointów na XY lokalne
                        full_mission_path_xy = []
                        for wp in full_mission_path_gps:
                            wx, wy = geo.gps_to_xy(wp['lat'], wp['lon'])
                            full_mission_path_xy.append((wx, wy))
                            
                        current_data["current_wp_index"] = 0
                        current_data["mission_status"] = "active"
        except Exception: pass

        time.sleep(dt)

if __name__ == "__main__":
    main()