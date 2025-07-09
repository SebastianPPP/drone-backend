import time
import requests
from pymavlink import mavutil

# Parametry połączenia MAVLink z Durandalem
# Zmień na właściwy port i prędkość, np. /dev/ttyUSB0, 115200 lub UDP itp.
MAVLINK_CONNECTION = 'udp:127.0.0.1:14550'  # przykład UDP lokalny; zmień na swoje

# URL Twojego backendu (Render, etc)
BACKEND_URL = "https://drone-backend-2-1mwz.onrender.com/api/telemetry"

def main():
    # nawiąż połączenie MAVLink
    master = mavutil.mavlink_connection(MAVLINK_CONNECTION)

    print("Oczekiwanie na heartbeat od Durandal...")
    master.wait_heartbeat()
    print(f"Połączono z systemem ID {master.target_system}")

    while True:
        # Odbierz wiadomość MAVLink, timeout=1s
        msg = master.recv_match(timeout=1)
        if not msg:
            print("Brak wiadomości MAVLink, czekam...")
            time.sleep(1)
            continue

        msg_type = msg.get_type()

        if msg_type == "GLOBAL_POSITION_INT":
            # Pozycja GPS
            lat = msg.lat / 1e7   # w stopniach
            lon = msg.lon / 1e7
            alt = msg.alt / 1000  # w metrach

            print(f"Pozycja: lat {lat}, lon {lon}, alt {alt}m")

            # Próba odczytu temperatury - MAVLink nie zawsze ma to w standardzie
            # Zakładam, że temperatura może przychodzić np. w SENSOR_OFFSETS lub innym niestandardowym komunikacie
            temperature = None

            # Tu możesz dodać kod do czytania temperatury z innego typu wiadomości

            data = {
                "drone_id": "durandal_1",
                "lat": lat,
                "lon": lon,
                "altitude": alt,
                "temperature": temperature,
                "mission_status": "active"
            }

            # Wyślij dane do backendu
            try:
                response = requests.post(BACKEND_URL, json=data, timeout=5)
                if response.status_code == 200:
                    print("Dane telemetryczne wysłane pomyślnie.")
                else:
                    print(f"Błąd serwera: {response.status_code} {response.text}")
            except requests.exceptions.RequestException as e:
                print(f"Błąd połączenia z backendem: {e}")

        # Możesz dodać obsługę innych typów wiadomości MAVLink, np. temperatury, status misji itd.

        time.sleep(1)  # delay, dostosuj według potrzeb


if __name__ == "__main__":
    main()
