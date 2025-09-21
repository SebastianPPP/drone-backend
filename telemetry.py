# BACKEND_URL = "https://drone-backend-2-1mwz.onrender.com/api/telemetry"

from pymavlink import mavutil
import requests
import time

# config
uart_port = "/dev/serial0"
baud_rate = 57600
BASE_URL = "http://127.0.0.1:5000"
DRONE_ID = "skimmer-1"

# Połącz z dronem przez MAVLink
master = mavutil.mavlink_connection(uart_port, baud=baud_rate)
master.wait_heartbeat()
print(f"Connected to drone {DRONE_ID}")

def send_telemetry(lat, lon, alt, battery):
    payload = {
        "drone_id": DRONE_ID,
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "battery": battery  
    }
    try:
        r = requests.post(f"{BASE_URL}/api/telemetry", json=payload)
        if r.status_code != 200:
            print("Telemetry error:", r.status_code, r.text)
    except Exception as e:
        print("Telemetry faulty:", e)

def fetch_mission():
    try:
        r = requests.get(f"{BASE_URL}/api/mission/current")
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print("Fault while fetching mission:", e)
    return {}

def confirm_mission():
    payload = {"droneId": DRONE_ID, "status": "received"}
    try:
        r = requests.post(f"{BASE_URL}/api/mission/status", json=payload)
        if r.status_code == 200:
            print("Mission confirmed")
    except Exception as e:
        print("Fault while confirming mission:", e)

def send_mavlink_mission(mission_points):
    master.waypoint_clear_all_send()

    for i, (lat, lon) in enumerate(mission_points):
        lat_int = int(lat * 1e7)
        lon_int = int(lon * 1e7)
        master.mav.send(mavutil.mavlink.MAVLink_mission_item_message(
            master.target_system,
            master.target_component,
            i,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
            mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
            0, 0, 0, 0, 0, 0,
            lat_int, lon_int, 0
        ))
        time.sleep(0.5)

    master.mav.mission_count_send(master.target_system, master.target_component, len(mission_points))
    print(f"Sent {len(mission_points)} mission points to drone")

mission_executed = False

while True:
    msg = master.recv_match(type=['GLOBAL_POSITION_INT', 'SYS_STATUS'], blocking=False)
    if msg:
        lat = getattr(msg, 'lat', None)
        lon = getattr(msg, 'lon', None)
        alt = getattr(msg, 'alt', None)
        battery = getattr(msg, 'battery', None)

        if lat and lon:
            send_telemetry(lat / 1e7, lon / 1e7, alt / 1000 if alt else 0, battery if battery else 0)

    mission = fetch_mission()
    if mission and not mission_executed:
        if DRONE_ID in mission:
            confirm_mission()
            send_mavlink_mission(mission[DRONE_ID])
            mission_executed = True
    time.sleep(0.5)