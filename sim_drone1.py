import requests
import time
import math
import numpy as np

# --- KONFIGURACJA ---
BACKEND_URL = "https://drone-backend-2-1mwz.onrender.com/api/telemetry"
API_KEY = "ZTBdrony"
DRONE_ID = "skimmer1"
START_LAT = 52.2297
START_LON = 21.0122

WP_TOLERANCE = 3.0  # Metry (zwiększyłem lekko dla płynności)

class LocalFrame:
    def __init__(self, lat0, lon0):
        self.lat0 = lat0
        self.lon0 = lon0
        self.R = 6371000 
    def gps_to_xy(self, lat, lon):
        x = (lon - self.lon0) * (np.pi/180) * self.R * np.cos(self.lat0 * np.pi/180)
        y = (lat - self.lat0) * (np.pi/180) * self.R
        return x, y
    def xy_to_gps(self, x, y):
        lat = self.lat0 + (y / self.R) * (180/np.pi)
        lon = self.lon0 + (x / (self.R * np.cos(self.lat0 * np.pi/180))) * (180/np.pi)
        return lat, lon

class AdaptiveFuzzyController:
    def __init__(self):
        self.K_PSI = 2.5
        self.K_Z = 25.0
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

        desired_psi = math.atan2(ty - y, tx - x)
        e_psi = desired_psi - psi
        e_psi = math.atan2(math.sin(e_psi), math.cos(e_psi))

        alpha_r = self.K_PSI * e_psi
        z_r = r - alpha_r

        xi = self._fuzzy_basis(z_r)
        d_theta = self.ETA * z_r * xi * dt
        self.theta += d_theta
        # Limit wag
        if np.linalg.norm(self.theta) > 50.0:
            self.theta *= 50.0 / np.linalg.norm(self.theta)

        fuzzy_comp = np.dot(self.theta, xi)
        torque_z = -self.K_Z * z_r - fuzzy_comp
        torque_z = max(min(torque_z, 100.0), -100.0)

        dist = math.hypot(tx - x, ty - y)
        
        # --- LOGIKA PRĘDKOŚCI ---
        target_speed = 12.0
        if abs(e_psi) > 0.5: target_speed = 4.0 # Zwalnia na zakrętach
        if dist < 15.0: target_speed = 3.0      # Zwalnia przy dolocie
        
        force_x = 250.0 * (target_speed - u)
        force_x = max(0.0, min(300.0, force_x))

        return force_x, torque_z

class PhysicsModel:
    def __init__(self):
        self.u = 0.0 
        self.r = 0.0 
        self.m = 20.0 
        self.I = 5.0  
        self.drag_u = 0.5 
        self.drag_r = 2.0 

    def step(self, fx, tz, dt):
        acc_u = (fx - self.drag_u * self.u) / self.m
        acc_r = (tz - self.drag_r * self.r) / self.I
        self.u += acc_u * dt
        self.r += acc_r * dt
        return self.u, self.r

def main():
    geo = LocalFrame(START_LAT, START_LON)
    logic = AdaptiveFuzzyController()
    physics = PhysicsModel()

    local_x, local_y = 0.0, 0.0
    yaw = 0.0
    
    # Stan drona
    current_data = {
        "lat": START_LAT, "lon": START_LON, "alt": 10.0, "battery": 100.0,
        "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
        "role": "None", "mission_id": None, "mission_status": "nothing",
        "current_wp_index": 0
    }
    
    full_mission_path_xy = []
    
    dt = 0.1 
    headers = {"X-Drone-Token": API_KEY, "Content-Type": "application/json"}

    print(f"--- Start LEADER: {DRONE_ID} ---", flush=True)

    while True:
        target_xy = None
        
        # --- 1. LOGIKA WYBORU CELU ---
        if current_data["mission_status"] == "active":
            if full_mission_path_xy and current_data["current_wp_index"] < len(full_mission_path_xy):
                target_xy = full_mission_path_xy[current_data["current_wp_index"]]
            else:
                # KONIEC TRASY -> ZMIANA STANU NA DONE
                print("🏁 Misja zakończona (osiągnięto ostatni punkt). Czekam.", flush=True)
                current_data["mission_status"] = "done"

        # --- 2. OBLICZENIA FIZYKI ---
        fx, tz = 0.0, 0.0
        
        if target_xy:
            # Lecimy do punktu
            state = {'x': local_x, 'y': local_y, 'yaw': yaw, 'r': physics.r, 'u': physics.u}
            fx, tz = logic.compute(state, target_xy, dt)
            
            # Sprawdzenie zaliczenia punktu
            dist_to_wp = math.hypot(target_xy[0] - local_x, target_xy[1] - local_y)
            if dist_to_wp < WP_TOLERANCE: 
                print(f"🎯 Zaliczo WP #{current_data['current_wp_index'] + 1}", flush=True)
                current_data["current_wp_index"] += 1
        elif current_data["mission_status"] == "done":
            # Tryb HOVER (wiszenie) - aktywne hamowanie
            fx = -20.0 * physics.u  # Hamuj prędkość liniową
            tz = -10.0 * physics.r  # Hamuj obrót
        
        # Krok fizyki
        physics.step(fx, tz, dt)
        local_x += physics.u * math.cos(yaw) * dt
        local_y += physics.u * math.sin(yaw) * dt
        yaw += physics.r * dt
        yaw = math.atan2(math.sin(yaw), math.cos(yaw))

        # Konwersja na GPS
        new_lat, new_lon = geo.xy_to_gps(local_x, local_y)
        current_data["battery"] = max(0, current_data["battery"] - 0.01)

        # --- 3. WYSYŁANIE TELEMETRII ---
        # Jeśli misja aktywna, pokazujemy nr WP, jeśli zakończona, pokazujemy "Koniec" (jako np. max+1)
        wp_display = 0
        if current_data["mission_status"] == "active":
            wp_display = current_data["current_wp_index"] + 1
        elif current_data["mission_status"] == "done":
            wp_display = 999 # Kod dla frontend, że koniec (lub po prostu ostatni znany)

        payload = {
            "drone_id": DRONE_ID,
            "lat": new_lat, "lon": new_lon, "alt": 10,
            "battery": round(current_data["battery"], 1),
            "roll": 0, "pitch": 0, "yaw": round(math.degrees(yaw), 2),
            "target_wp": wp_display
        }

        try:
            resp = requests.post(BACKEND_URL, json=payload, headers=headers, timeout=1)
            
            if resp.status_code == 200:
                data = resp.json()
                
                # --- 4. ODBIÓR NOWEJ MISJI I AKTUALIZACJA W LOCIE ---
                server_mission = data.get("mission")
                
                # Jeśli serwer ma misję, a my mamy inną ID (lub wcale)
                if server_mission:
                    msn_id = server_mission.get("id")
                    if msn_id != current_data["mission_id"]:
                        print(f"📜 Aktualizacja misji! ID: {msn_id}", flush=True)
                        current_data["mission_id"] = msn_id
                        
                        # Przeliczamy nowe punkty
                        raw_wps = server_mission.get("waypoints", [])
                        new_path_xy = []
                        for wp in raw_wps:
                            wx, wy = geo.gps_to_xy(wp[0], wp[1])
                            new_path_xy.append((wx, wy))
                        
                        full_mission_path_xy = new_path_xy
                        current_data["mission_status"] = "active"
                        
                        # === SMART RESUME (Znajdź najbliższy punkt) ===
                        # Zamiast resetować do 0, znajdźmy najbliższy punkt w nowej trasie
                        best_idx = 0
                        min_dist = float('inf')
                        
                        # Sprawdzamy, który punkt z NOWEJ trasy jest najbliżej obecnej pozycji drona
                        for i, (wx, wy) in enumerate(full_mission_path_xy):
                            d = math.hypot(wx - local_x, wy - local_y)
                            if d < min_dist:
                                min_dist = d
                                best_idx = i
                        
                        # Ustawiamy cel na ten punkt (lub następny, jeśli jesteśmy bardzo blisko)
                        current_data["current_wp_index"] = best_idx
                        print(f"🔄 Wznawiam od punktu #{best_idx + 1} (Najbliższy)", flush=True)

                elif not server_mission and current_data["mission_status"] in ["active", "done"]:
                     # Użytkownik kliknął STOP
                     print("🛑 Komenda STOP.", flush=True)
                     current_data["mission_status"] = "nothing"
                     current_data["mission_id"] = None
                     full_mission_path_xy = []
                     
        except Exception:
            pass
            
        time.sleep(dt)

if __name__ == "__main__":
    main()