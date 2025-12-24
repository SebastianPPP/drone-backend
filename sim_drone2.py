import requests
import time
import math
import numpy as np

# --- KONFIGURACJA ---
BACKEND_URL_DRONES = "https://drone-backend-2-1mwz.onrender.com/api/drones"
BACKEND_URL_TELEM = "https://drone-backend-2-1mwz.onrender.com/api/telemetry"

API_KEY = "ZTBdrony"
DRONE_ID = "follower1"
LEADER_ID = "skimmer1" 
START_LAT = 52.2297
START_LON = 21.0120 

TARGET_DISTANCE = 8.0   
ZONE_RED = 3.0          

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

        if real_dist_to_leader < ZONE_RED:
            # Hamowanie awaryjne
            return -200.0, 0.0 

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
        
        dist_to_virtual = math.hypot(tx - x, ty - y)
        force_x = 0.0
        MAX_TORQUE = 80.0
        
        if abs(e_psi) > 0.8:
            force_x = 0.0
            MAX_TORQUE = 100.0
        elif abs_angle_err := abs(e_psi) > 0.35:
            force_x = 40.0
            MAX_TORQUE = 60.0
        else:
            desired_speed = 3.5 * dist_to_virtual 
            desired_speed = min(desired_speed, 12.0)
            
            force_error = desired_speed - u
            force_x = 200.0 * force_error
            MAX_TORQUE = 40.0 

        torque_z = max(min(torque_z, MAX_TORQUE), -MAX_TORQUE)
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

    local_x, local_y = -10.0, -10.0 
    yaw = 0.0
    
    current_data = {"role": "follower", "battery": 95.0}
    dt = 0.1
    headers = {"X-Drone-Token": API_KEY, "Content-Type": "application/json"}
    
    print(f"--- Start FOLLOWER: {DRONE_ID} ---", flush=True)

    while True:
        leader_state = None
        
        try:
            resp = requests.get(BACKEND_URL_DRONES, timeout=2)
            if resp.status_code == 200:
                drones = resp.json()
                for d in drones:
                    if d.get('drone_id') == LEADER_ID:
                        leader_state = d
                        break
        except Exception: 
            pass

        fx, tz = 0.0, 0.0

        if leader_state:
            l_lat, l_lon = leader_state['lat'], leader_state['lon']
            l_yaw_rad = math.radians(leader_state.get('yaw', 0))
            
            lx, ly = geo.gps_to_xy(l_lat, l_lon)
            
            target_x = lx - TARGET_DISTANCE * math.cos(l_yaw_rad)
            target_y = ly - TARGET_DISTANCE * math.sin(l_yaw_rad)
            
            state = {'x': local_x, 'y': local_y, 'yaw': yaw, 'r': physics.r, 'u': physics.u}
            fx, tz = logic.compute(state, (target_x, target_y), (lx, ly), dt)
        else:
            # Brak lidera - HOVER
            fx = -20.0 * physics.u
            tz = -10.0 * physics.r

        physics.step(fx, tz, dt)
        local_x += physics.u * math.cos(yaw) * dt
        local_y += physics.u * math.sin(yaw) * dt
        yaw += physics.r * dt
        yaw = math.atan2(math.sin(yaw), math.cos(yaw))

        new_lat, new_lon = geo.xy_to_gps(local_x, local_y)
        current_data["battery"] = max(0, current_data["battery"] - 0.01)
        
        payload = {
            "drone_id": DRONE_ID,
            "lat": new_lat, "lon": new_lon, "alt": 10,
            "battery": round(current_data["battery"], 1),
            "yaw": round(math.degrees(yaw), 2),
            "roll": 0, "pitch": 0,
            "target_wp": 0 
        }
        
        try:
            requests.post(BACKEND_URL_TELEM, json=payload, headers=headers, timeout=1)
        except Exception: pass
        
        time.sleep(dt)

if __name__ == "__main__":
    main()