"""
sim_leader.py — Symulator drona-lidera "skimmer1"
Lata po okręgu i wysyła telemetrię do GCS.
Follower (follower1) podąża za nim automatycznie.

Uzycie:
    python3 sim_leader.py
    python3 sim_leader.py --id skimmer1 --radius 0.0008 --speed 1.5
"""

import requests
import time
import math
import argparse
import random
import sys

parser = argparse.ArgumentParser(description="Symulator lidera")
parser.add_argument("--host",   default="drone-backend-2-1mwz.onrender.com", help="Host GCS")
parser.add_argument("--id",     default="skimmer1",   help="ID lidera")
parser.add_argument("--token",  default="ZTBdrony",   help="X-Drone-Token")
parser.add_argument("--lat",    default=52.2297, type=float)
parser.add_argument("--lon",    default=21.0122, type=float)
parser.add_argument("--radius", default=0.0006, type=float, help="Promien okrego (stopnie)")
parser.add_argument("--alt",    default=30.0,   type=float, help="Wysokosc (m)")
parser.add_argument("--speed",  default=1.0,    type=float, help="Predkosc katowa")
args = parser.parse_args()

BASE_URL = "https://{}".format(args.host)
ENDPOINT = BASE_URL + "/api/telemetry"
HEADERS  = {"Content-Type": "application/json", "X-Drone-Token": args.token}

COLORS = {
    "reset":  "\033[0m",
    "green":  "\033[92m",
    "yellow": "\033[93m",
    "red":    "\033[91m",
    "cyan":   "\033[96m",
    "blue":   "\033[94m",
    "dim":    "\033[2m",
}
def c(color, text):
    return COLORS.get(color, "") + str(text) + COLORS["reset"]

print(c("blue", """
+------------------------------------------+
|     GCS LEADER SIMULATOR // skimmer1     |
+------------------------------------------+"""))
print(c("blue", "  ID     : " + args.id))
print(c("blue", "  Server : " + BASE_URL))
print(c("blue", "  Orbit  : {:.4f}, {:.4f}".format(args.lat, args.lon)))
print(c("blue", "+------------------------------------------+\n"))
print(c("dim", "Ctrl+C aby zatrzymac\n"))

battery = 100.0
angle   = 0.0
tick    = 0
errors  = 0

while True:
    tick  += 1
    angle += 0.025 * args.speed

    lat = args.lat + math.sin(angle) * args.radius
    lon = args.lon + math.cos(angle) * args.radius
    yaw = (math.degrees(angle + math.pi / 2)) % 360
    alt = args.alt + math.sin(angle * 0.7) * 2 + random.uniform(-0.3, 0.3)

    roll  = math.sin(angle * 2) * 6 + random.uniform(-1, 1)
    pitch = math.cos(angle * 3) * 4 + random.uniform(-1, 1)

    battery -= random.uniform(0.005, 0.02)
    battery  = max(0.0, battery)

    if battery > 40:
        bat_color = "green"
    elif battery > 20:
        bat_color = "yellow"
    else:
        bat_color = "red"

    payload = {
        "drone_id":  args.id,
        "lat":       round(lat, 7),
        "lon":       round(lon, 7),
        "alt":       round(alt, 1),
        "battery":   round(battery, 1),
        "roll":      round(roll, 2),
        "pitch":     round(pitch, 2),
        "yaw":       round(yaw, 1),
        "target_wp": 0,
    }

    try:
        resp = requests.post(ENDPOINT, json=payload, headers=HEADERS, timeout=3)

        if resp.status_code == 200:
            errors = 0
            lat_s = "{:.5f}".format(payload["lat"])
            lon_s = "{:.5f}".format(payload["lon"])
            yaw_s = "{:>5.1f}deg".format(payload["yaw"])
            bat_s = "{:>5.1f}%".format(payload["battery"])

            print(
                c("dim",  "[{:>4}]".format(tick)) + " " +
                c("blue", "LEADER " + args.id) +
                c("dim",  "  |  ") +
                "LAT " + c("cyan", lat_s) + "  " +
                "LON " + c("cyan", lon_s) + "  " +
                "YAW " + c("dim",  yaw_s) + "  " +
                "BAT " + c(bat_color, bat_s)
            )
        elif resp.status_code == 401:
            print(c("red", "[BLAD 401] Zly token!"))
            sys.exit(1)
        else:
            print(c("red", "[BLAD {}] {}".format(resp.status_code, resp.text[:60])))
            errors += 1

    except requests.exceptions.ConnectionError:
        errors += 1
        print(c("red", "[BRAK POLACZENIA] proba {}...".format(errors)))
        if errors >= 10:
            sys.exit(1)

    except requests.exceptions.Timeout:
        print(c("yellow", "[TIMEOUT]"))
        errors += 1

    except KeyboardInterrupt:
        print(c("blue", "\nLEADER ZATRZYMANY po {} tickach.".format(tick)))
        sys.exit(0)

    time.sleep(0.1)