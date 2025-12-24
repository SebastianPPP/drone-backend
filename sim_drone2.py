import requests
import time
import math
import numpy as np

# --- CONFIG ---
BACKEND_URL = "https://drone-backend-2-1mwz.onrender.com/api/telemetry"
DRONE_ID = "sim_drone_2"
LEADER_ID = "sim_drone_1"
START_LAT = 52.1000
START_LON = 19.2995 

TARGET_DISTANCE = 4.0   
ZONE_RED = 2.5     # Odległość krytyczna (hamowanie awaryjne)
ZONE_YELLOW = 6.0  # Odległość ostrzegawcza (zaczynamy zwalniać)

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
        self.K_Z = 20.0    
        self.ETA = 2.0     
        self.num_rules = 11
        self.centers = np.linspace(-2.0, 2.0, self.num_rules)
        self.width = 2.0
        self.theta = np.zeros(self.num_rules)

    def _fuzzy_basis(self, error_val):
        basis = np.exp(-(error_val - self.centers) ** 2 / (self.width ** 2))
        norm = np.sum(basis)
        return basis / norm if norm > 0.0001 else basis

    def compute(self, current_state, target_wp, actual_leader_pos, dt=0.05):
        x, y = current_state['x'], current_state['y']
        psi = current_state['yaw']
        r = current_state['r']
        u = current_state['u']
        tx, ty = target_wp
        lx, ly = actual_leader_pos

        real_dist_to_leader = math.hypot(lx - x, ly - y)

        # --- 1. UNIKANIE KOLIZJI (ODPYCHANIE) ---
        # Jeśli jesteśmy za blisko lidera (nie wirtualnego punktu, tylko fizycznego drona)
        if real_dist_to_leader < ZONE_RED:
            # Bardzo mocne "wsteczne" - odpychanie
            print(f"🚨 KOLIZJA! Hamowanie awaryjne ({real_dist_to_leader:.2f}m)", flush=True)
            return -300.0, 0.0 

        # --- 2. KĄT I FUZZY ---
        desired_psi = math.atan2(ty - y, tx - x)
        e_psi = desired_psi - psi
        e_psi = math.atan2(math.sin(e_psi), math.cos(e_psi)) 

        alpha_r = self.K_PSI * e_psi
        z_r = r - alpha_r
        xi = self._fuzzy_basis(z_r)
        d_theta = self.ETA * z_r * xi * dt
        self.theta += d_theta
        if np.linalg.norm(self.theta) > 30.0:
            self.theta *= 30.0 / np.linalg.norm(self.theta)
        fuzzy_comp = np.dot(self.theta, xi)
        torque_z = -self.K_Z * z_r - fuzzy_comp
        
        # --- 3. PIVOT TURN I PRĘDKOŚĆ ---
        abs_angle_err = abs(e_psi)
        dist_to_virtual = math.hypot(tx - x, ty - y)
        force_x = 0.0
        
        MAX_TORQUE = 80.0
        
        # Jeśli trzeba się mocno obrócić -> Pivot
        if abs_angle_err > 0.8:
            force_x = 0.0
            MAX_TORQUE = 100.0
        elif abs_angle_err > 0.35:
            force_x = 40.0 # Trochę szybciej na zakręcie niż wcześniej
            MAX_TORQUE = 60.0
        else:
            # --- ZMIANA: PRĘDKOŚĆ ---
            # Follower ma być szybki (do 12 m/s), żeby dogonić Lidera
            desired_speed = 3.5 * dist_to_virtual 
            desired_speed = min(desired_speed, 12.0) # Max 12 m/s
            
            force_error = desired_speed - u
            force_x = 200.0 * force_error # Duża moc silnika
            MAX_TORQUE = 40.0 

        torque_z = max(min(torque_z, MAX_TORQUE), -MAX_TORQUE)

        # --- 4. ZWALNIANIE PRZED KOLIZJĄ (ZONE YELLOW) ---
        if real_dist_to_leader < ZONE_YELLOW:
            # Jeśli zbliżamy się do strefy żółtej, drastycznie tniemy gaz
            # A jeśli lecimy szybko (>3m/s), włączamy hamulec
            limit = 30.0 * (real_dist_to_leader - ZONE_RED) # Im bliżej, tym mniejszy limit
            force_x = min(force_x, limit)
            
            if u > 4.0: 
                force_x = -100.0 # Aktywne hamowanie

        force_x = max(-300.0, force_x) # Limit wstecznego
        force_x = min(force_x, 300.0)  # Limit do przodu

        return force_x, torque_z

class PhysicsModel:
    def __init__(self):
        self.u, self.r = 0.0, 0.0
        self.m, self.I = 20.0, 5.0
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

    local_x, local_y = -30.0, 0.0 
    yaw = 0.0
    
    current_data = {
        "lat": START_LAT, "lon": START_LON, 
        "role": "follower", "mission_status": "nothing", "mission_id": None
    }
    
    dt = 0.1
    print(f"--- Start FOLLOWER (Speed 12m/s, Anti-Coll) ---", flush=True)

    while True:
        leader_state = None
        try:
            resp = requests.get(BACKEND_URL) 
            if resp.status_code == 200:
                all_drones = resp.json()
                for d in all_drones:
                    if d['drone_id'] == LEADER_ID:
                        leader_state = d
                        break
        except Exception: pass

        fx, tz = 0.0, 0.0

        if leader_state and current_data["role"] == "follower":
            l_lat, l_lon = leader_state['lat'], leader_state['lon']
            l_yaw_rad = math.radians(leader_state['yaw'])
            
            lx, ly = geo.gps_to_xy(l_lat, l_lon)
            
            target_x = lx - TARGET_DISTANCE * math.cos(l_yaw_rad)
            target_y = ly - TARGET_DISTANCE * math.sin(l_yaw_rad)
            
            state = {'x': local_x, 'y': local_y, 'yaw': yaw, 'r': physics.r, 'u': physics.u}
            # Przekazujemy pozycję lidera (lx, ly) do unikania kolizji
            fx, tz = logic.compute(state, (target_x, target_y), (lx, ly), dt)

        physics.step(fx, tz, dt)
        local_x += physics.u * math.cos(yaw) * dt
        local_y += physics.u * math.sin(yaw) * dt
        yaw += physics.r * dt
        yaw = math.atan2(math.sin(yaw), math.cos(yaw))

        new_lat, new_lon = geo.xy_to_gps(local_x, local_y)
        
        payload = {
            "drone_id": DRONE_ID,
            "lat": new_lat, "lon": new_lon, "alt": 10,
            "battery": 90,
            "yaw": round(math.degrees(yaw), 2),
            "role": current_data["role"],
            "mission_status": ("active", current_data["mission_id"]) if leader_state else ("nothing", None),
            "next_waypoints": [] 
        }
        
        try:
            resp = requests.post(BACKEND_URL, json=payload, timeout=1)
            if resp.status_code == 200:
                data = resp.json()
                if "role" in data: current_data["role"] = data["role"]
        except Exception: pass
        time.sleep(dt)

if __name__ == "__main__":
    main()