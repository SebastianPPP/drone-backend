import time
import threading
import math
import requests
import sys

# --- KONFIGURACJA ---
SERVER_URL = 'https://drone-backend-2-1mwz.onrender.com'
API_KEY = 'ZTBdrony'
DRONE_ID = 'skimmer1'

# Ustawienia symulacji
START_LAT = 52.2297   # Warszawa
START_LON = 21.0122
SPEED_FACTOR = 0.0001 # Prędkość ruchu
TELEMETRY_RATE = 1.0  # Częstotliwość (s)
SIMULATION_TICK = 0.05

class DroneSimulator:
    def __init__(self, drone_id, start_lat, start_lon):
        self.drone_id = drone_id
        self.lat = start_lat
        self.lon = start_lon
        self.alt = 0
        self.battery = 100.0
        self.heading = 0
        
        # Logika misji
        self.mission_waypoints = []  
        self.wp_index = 0  # <--- NOWOŚĆ: Licznik punktów
        self.status = 'Idle' 
        self.running = True

        print(f"--- SYMULATOR DRONA: {self.drone_id} ---")
        print(f"Serwer: {SERVER_URL}")
        print("Uruchamianie...")

    def start(self):
        movement_thread = threading.Thread(target=self._movement_loop, daemon=True)
        movement_thread.start()
        self._telemetry_loop()

    def _telemetry_loop(self):
        uri = f"{SERVER_URL}/api/telemetry"
        headers = {"X-Drone-Token": API_KEY}

        while self.running:
            self.battery = max(0, self.battery - 0.02)
            
            # Jeśli mamy misję, wysyłamy numer punktu do którego lecimy (1, 2, 3...)
            # Jeśli nie ma misji, wysyłamy 0
            current_target_number = self.wp_index + 1 if self.mission_waypoints else 0

            payload = {
                "drone_id": self.drone_id,
                "lat": self.lat,
                "lon": self.lon,
                "alt": self.alt,
                "battery": round(self.battery, 1),
                "roll": 0, "pitch": 0, "yaw": self.heading,
                "target_wp": current_target_number # <--- WYSYŁAMY TO DO SERWERA
            }

            try:
                # Timeout 10s żeby nie wisiał w nieskończoność
                response = requests.post(uri, json=payload, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    self._handle_server_commands(data)
                    
                    status_info = f"Cel: WP #{current_target_number}" if self.mission_waypoints else self.status
                    print(f"[{self.drone_id}] Telemetria OK | Bat: {payload['battery']}% | {status_info}")
                
                elif response.status_code == 401:
                    print(f"!! BŁĄD AUTORYZACJI !! Klucz odrzucony.")

            except Exception as e:
                print(f"Błąd połączenia: {e}")

            time.sleep(TELEMETRY_RATE)

    def _handle_server_commands(self, data):
        server_mission = data.get('mission')
        
        # START MISJI
        if server_mission and not self.mission_waypoints:
            waypoints = server_mission.get('waypoints', [])
            if waypoints:
                print(f"\n>>> START MISJI! Punktów: {len(waypoints)} <<<\n")
                self.mission_waypoints = waypoints
                self.wp_index = 0 # Resetujemy licznik
                self.status = 'Mission'

        # STOP MISJI
        if not server_mission and self.mission_waypoints:
             print("\n>>> STOP MISJI <<<\n")
             self.mission_waypoints = []
             self.wp_index = 0
             self.status = 'Idle'

    def _movement_loop(self):
        while self.running:
            if self.mission_waypoints:
                self._fly_logic()
            time.sleep(SIMULATION_TICK)

    def _fly_logic(self):
        # Sprawdzamy czy nie skończyły się punkty
        if self.wp_index >= len(self.mission_waypoints):
            self.status = 'Hover' # Koniec trasy
            return

        # Pobieramy współrzędne aktualnego celu
        target = self.mission_waypoints[self.wp_index] # [lat, lon]
        target_lat = target[0]
        target_lon = target[1]
        
        lat_diff = target_lat - self.lat
        lon_diff = target_lon - self.lon
        dist = math.sqrt(lat_diff**2 + lon_diff**2)

        self.heading = (math.degrees(math.atan2(lon_diff, lat_diff)) + 360) % 360

        if dist < SPEED_FACTOR:
            # Dolecieliśmy do punktu -> Zwiększamy licznik
            print(f">>> Osiągnięto WP #{self.wp_index + 1}")
            self.wp_index += 1
        else:
            # Lecimy dalej
            self.lat += (lat_diff / dist) * SPEED_FACTOR
            self.lon += (lon_diff / dist) * SPEED_FACTOR

if __name__ == '__main__':
    sim = DroneSimulator(DRONE_ID, START_LAT, START_LON)
    sim.start()