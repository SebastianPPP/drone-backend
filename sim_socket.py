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
TELEMETRY_RATE = 1.0  # Częstotliwość wysyłania danych (s)
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
        self.current_target = None   
        self.status = 'Idle' 
        self.running = True

        print(f"--- SYMULATOR DRONA: {self.drone_id} ---")
        print(f"Serwer: {SERVER_URL}")
        print("Uruchamianie...")

    def start(self):
        """Uruchamia wątki symulacji."""
        # Wątek fizyki (ruch)
        movement_thread = threading.Thread(target=self._movement_loop, daemon=True)
        movement_thread.start()
        
        # Pętla główna (komunikacja z serwerem)
        self._telemetry_loop()

    def _telemetry_loop(self):
        """Wysyła dane do serwera i odbiera rozkazy."""
        uri = f"{SERVER_URL}/api/telemetry"
        headers = {"X-Drone-Token": API_KEY}

        while self.running:
            # 1. Przygotuj dane
            self.battery = max(0, self.battery - 0.02)
            payload = {
                "drone_id": self.drone_id,
                "lat": self.lat,
                "lon": self.lon,
                "alt": self.alt,
                "battery": round(self.battery, 1),
                "roll": 0, "pitch": 0, "yaw": self.heading
            }

            try:
                # 2. Wyślij POST do serwera
                response = requests.post(uri, json=payload, headers=headers, timeout=60)                
                if response.status_code == 200:
                    data = response.json()
                    # 3. Odczytaj rozkazy z odpowiedzi
                    self._handle_server_commands(data)
                    print(f"[{self.drone_id}] Telemetria OK | Bat: {payload['battery']}% | Stan: {self.status}")
                elif response.status_code == 401:
                    print(f"!! BŁĄD AUTORYZACJI !! Serwer odrzucił klucz: {API_KEY}")
                else:
                    print(f"Błąd serwera: {response.status_code}")

            except requests.exceptions.ConnectionError:
                print("Nie można połączyć z serwerem. Czy adres jest poprawny?")
            except Exception as e:
                print(f"Błąd: {e}")

            time.sleep(TELEMETRY_RATE)

    def _handle_server_commands(self, data):
        """Analizuje odpowiedź serwera."""
        server_mission = data.get('mission')
        
        # Jeśli serwer przysłał misję, a my jej jeszcze nie mamy -> START
        if server_mission and not self.mission_waypoints and not self.current_target:
            waypoints = server_mission.get('waypoints', [])
            if waypoints:
                print(f"\n>>> OTRZYMANO MISJĘ! Liczba punktów: {len(waypoints)} <<<\n")
                self.mission_waypoints = waypoints
                self.status = 'Mission'

        # Jeśli serwer anulował misję (brak obiektu mission), a my lecimy -> STOP
        if not server_mission and (self.mission_waypoints or self.current_target):
             print("\n>>> SERWER ANULOWAŁ MISJĘ (STOP) <<<\n")
             self.mission_waypoints = []
             self.current_target = None
             self.status = 'Idle'

    def _movement_loop(self):
        """Fizyka lotu."""
        while self.running:
            if self.mission_waypoints or self.current_target:
                self._fly_logic()
            time.sleep(SIMULATION_TICK)

    def _fly_logic(self):
        # Pobierz cel
        if not self.current_target and self.mission_waypoints:
            next_wp = self.mission_waypoints.pop(0)
            self.current_target = {'lat': next_wp[0], 'lon': next_wp[1]}
            
        if self.current_target:
            # Oblicz wektor
            target_lat = self.current_target['lat']
            target_lon = self.current_target['lon']
            
            lat_diff = target_lat - self.lat
            lon_diff = target_lon - self.lon
            dist = math.sqrt(lat_diff**2 + lon_diff**2)

            # Oblicz kąt (heading)
            self.heading = (math.degrees(math.atan2(lon_diff, lat_diff)) + 360) % 360

            if dist < SPEED_FACTOR:
                # Dolecieliśmy
                self.lat = target_lat
                self.lon = target_lon
                self.current_target = None
            else:
                # Lecimy
                self.lat += (lat_diff / dist) * SPEED_FACTOR
                self.lon += (lon_diff / dist) * SPEED_FACTOR
        else:
            self.status = 'Hover'

if __name__ == '__main__':
    sim = DroneSimulator(DRONE_ID, START_LAT, START_LON)
    sim.start()