import requests
import time
import math
import random

# Konfiguracja
SERVER_URL = "http://localhost:5000/api/telemetry"
DRONE_ID = "sim_drone_1"

# Startowa pozycja (Centrum Warszawy)
start_lat = 52.2297
start_lon = 21.0122

def run_simulation():
    print(f"🚀 Uruchamiam symulację drona: {DRONE_ID}")
    print(f"📡 Cel: {SERVER_URL}")
    print("Naciśnij Ctrl+C, aby zatrzymać.")

    angle = 0
    radius = 0.002 # Promień koła (w stopniach geograficznych)
    altitude = 0
    
    try:
        while True:
            # --- 1. OBLICZANIE FIZYKI (Symulacja lotu w kółko) ---
            
            # Przesuwanie po okręgu
            angle += 0.05 # Szybkość obrotu
            
            # Nowa pozycja GPS
            current_lat = start_lat + (radius * math.sin(angle))
            current_lon = start_lon + (radius * math.cos(angle)) * 1.6 # Korekta na szerokość geograficzną
            
            # Symulacja zmiany wysokości (góra/dół)
            altitude = 50 + (10 * math.sin(angle / 2))
            
            # Symulacja Yaw (Dziób drona patrzy zgodnie z kierunkiem lotu)
            # Math.atan2 zwraca radiany, zamieniamy na stopnie + korekta, żeby 0 to była północ
            yaw = math.degrees(math.atan2(math.cos(angle), -math.sin(angle)))
            
            # Symulacja przechyłów (żeby HUD ładnie "pracował")
            roll = 15 * math.sin(angle * 2)  # Bujanie na boki
            pitch = 5 * math.cos(angle * 3)  # Bujanie przód-tył

            # Symulacja baterii
            battery = 95

            # --- 2. BUDOWANIE PAYLOADU ---
            payload = {
                "drone_id": DRONE_ID,
                "lat": current_lat,
                "lon": current_lon,
                "alt": altitude,
                "battery": battery,
                "roll": roll,
                "pitch": pitch,
                "yaw": yaw,
                "role": "Simulated",
                "mission_status": "flying"
            }

            # --- 3. WYSYŁANIE DO SERWERA ---
            try:
                response = requests.post(SERVER_URL, json=payload, timeout=0.5)
                if response.status_code == 200:
                    data = response.json()
                    assigned_role = data.get("role", "None")
                    print(f"✅ Wysłano | Yaw: {int(yaw)}° | Rola od serwera: {assigned_role}", end="\r")
                else:
                    print(f"⚠️ Błąd serwera: {response.status_code}")
            except requests.exceptions.RequestException:
                print("❌ Nie można połączyć z serwerem (czy app_socket.py działa?)")

            # --- 4. CZEKANIE (Symulacja 10Hz) ---
            time.sleep(0.01) 

    except KeyboardInterrupt:
        print("\n🛑 Zatrzymano symulację.")

if __name__ == "__main__":
    # Sprawdzenie czy mamy bibliotekę requests
    try:
        import requests
    except ImportError:
        print("Brakuje biblioteki 'requests'. Zainstaluj ją: pip install requests")
        exit()
        
    run_simulation()