
#!/usr/bin/env python3
"""
drone_sim.py — prosty generator telemetrii "udający" drona.

Przykłady:
  1) Stała trasa z punktów inline (lon,lat;lon,lat), co 1 s:
     python drone_sim.py --server http://localhost:5000 --drone-id alpha \
       --waypoints "21.0000,52.2300;21.0050,52.2310;21.0100,52.2350" --interval 1

  2) Trasa z CSV (kolumny: lon,lat[,alt]), powtarzana w pętli:
     python drone_sim.py --server http://localhost:5000 --drone-id beta \
       --csv telemetry_sample.csv --interval 1.5 --repeat

  3) Losowy "random-walk" wokół punktu startowego:
     python drone_sim.py --server http://localhost:5000 --drone-id gamma \
       --random-walk 52.2300 21.0000 --step-m 15 --interval 0.8

Zakłada endpoint POST /api/telemetry przyjmujący JSON:
{ "drone_id", "lat", "lon", "alt", "battery", "roll", "pitch", "yaw" }
"""

import argparse
import csv
import json
import math
import random
import sys
import time
from typing import List, Tuple, Optional

try:
    import requests
except Exception as e:
    print("Ten skrypt wymaga pakietu 'requests': pip install requests", file=sys.stderr)
    raise

# --- Pomocnicze ---

def haversine_step(lat: float, lon: float, bearing_deg: float, step_m: float) -> Tuple[float, float]:
    """Przesuń punkt o 'step_m' metrów w kierunku 'bearing_deg' (WGS84)."""
    R = 6371000.0  # promień Ziemi [m]
    bearing = math.radians(bearing_deg)
    d_over_R = step_m / R
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)

    lat2 = math.asin(math.sin(lat1)*math.cos(d_over_R) + math.cos(lat1)*math.sin(d_over_R)*math.cos(bearing))
    lon2 = lon1 + math.atan2(math.sin(bearing)*math.sin(d_over_R)*math.cos(lat1),
                              math.cos(d_over_R)-math.sin(lat1)*math.sin(lat2))
    return (math.degrees(lat2), (math.degrees(lon2)+540) % 360 - 180)  # normalizacja do [-180,180]

def parse_waypoints_inline(s: str) -> List[Tuple[float, float, Optional[float]]]:
    pts = []
    for part in s.split(';'):
        part = part.strip()
        if not part:
            continue
        comps = [c.strip() for c in part.split(',')]
        if len(comps) < 2:
            raise ValueError(f"Nieprawidłowy punkt: '{part}' (oczekiwano lon,lat[,alt])")
        lon = float(comps[0]); lat = float(comps[1])
        alt = float(comps[2]) if len(comps) >= 3 and comps[2] != '' else None
        pts.append((lon, lat, alt))
    return pts

def load_csv(path: str) -> List[Tuple[float, float, Optional[float]]]:
    pts = []
    with open(path, newline='', encoding='utf-8') as f:
        rdr = csv.DictReader(f)
        if 'lon' not in rdr.fieldnames or 'lat' not in rdr.fieldnames:
            raise ValueError("CSV musi zawierać kolumny: lon,lat[,alt]")
        for row in rdr:
            lon = float(row['lon'])
            lat = float(row['lat'])
            alt = float(row.get('alt')) if row.get('alt') not in (None, '',) else None
            pts.append((lon, lat, alt))
    if not pts:
        raise ValueError("Brak punktów w CSV")
    return pts

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

# --- Główna pętla ---

def send_point(session: requests.Session, server: str, drone_id: str, lat: float, lon: float,
               alt: Optional[float], battery: float, noise_m: float, roll: float, pitch: float, yaw: float,
               headers: dict, timeout: float, verify_ssl: bool) -> bool:
    # dodaj szum (prostą aproksymacją 1e-5 ~ 1.1 m w PL)
    if noise_m > 0:
        # Przybliżenie 1e-5 stopnia szer/dł ~ 1.1 m w PL
        jitter_deg = noise_m / 1.1e5
        lat += random.uniform(-jitter_deg, jitter_deg)
        lon += random.uniform(-jitter_deg, jitter_deg)

    payload = {
        "drone_id": drone_id,
        "lat": lat,
        "lon": lon,
        "alt": float(alt) if alt is not None else None,
        "battery": round(battery, 1),
        "roll": round(roll, 2),
        "pitch": round(pitch, 2),
        "yaw": round(yaw % 360, 1)
    }
    # usuń None (jeśli serwer nie toleruje)
    payload = {k: v for k, v in payload.items() if v is not None}

    try:
        r = session.post(f"{server.rstrip('/')}/api/telemetry", json=payload,
                         timeout=timeout, headers=headers, verify=verify_ssl)
        ok = 200 <= r.status_code < 300
        print(f"[{time.strftime('%H:%M:%S')}] POST {r.status_code} {r.text.strip()[:200]}  ->  {payload}")
        return ok
    except Exception as e:
        print(f"POST błąd: {e}", file=sys.stderr)
        return False

def iter_path_points(pts: List[Tuple[float, float, Optional[float]]], repeat: bool):
    while True:
        for (lon, lat, alt) in pts:
            yield (lon, lat, alt)
        if not repeat:
            break

def run(args):
    session = requests.Session()
    headers = {}
    if args.auth_header:
        # np. "Authorization: Bearer XYZ"
        k, v = args.auth_header.split(":", 1)
        headers[k.strip()] = v.strip()

    # wybór źródła punktów
    points: List[Tuple[float, float, Optional[float]]] = []
    if args.csv:
        points = load_csv(args.csv)
    elif args.waypoints:
        points = parse_waypoints_inline(args.waypoints)
    elif args.random_walk:
        lat0, lon0 = args.random_walk
        points = [(lon0, lat0, args.alt)]
    else:
        raise SystemExit("Podaj --csv, --waypoints lub --random-walk LAT LON")

    battery = float(args.battery_start)
    yaw = float(args.yaw)
    roll = float(args.roll)
    pitch = float(args.pitch)

    if args.random_walk:
        # tryb spaceru losowego
        lat, lon = points[0][1], points[0][0]
        alt = args.alt
        while True:
            ok = send_point(session, args.server, args.drone_id, lat, lon, alt,
                            battery, args.noise_m, roll, pitch, yaw,
                            headers, args.timeout, not args.insecure)
            time.sleep(args.interval)
            # zmiany orientacji i baterii
            yaw = (yaw + random.uniform(-10, 10)) % 360
            battery = clamp(battery - args.battery_drain_per_tick, 0, 100)
            if battery <= 0 and not args.ignore_battery:
                print("Bateria rozładowana — stop.")
                break
            # krok
            bearing = random.uniform(0, 360)
            lat, lon = haversine_step(lat, lon, bearing, args.step_m)
    else:
        # tryb ścieżki
        for (lon, lat, alt) in iter_path_points(points, args.repeat):
            ok = send_point(session, args.server, args.drone_id, lat, lon, alt,
                            battery, args.noise_m, roll, pitch, yaw,
                            headers, args.timeout, not args.insecure)
            time.sleep(args.interval)
            yaw = (yaw + args.yaw_per_tick) % 360
            battery = clamp(battery - args.battery_drain_per_tick, 0, 100)
            if battery <= 0 and not args.ignore_battery:
                print("Bateria rozładowana — stop.")
                break

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Symulator telemetrii drona → POST /api/telemetry")
    p.add_argument("--server", default="http://localhost:5000", help="URL serwera Flask")
    p.add_argument("--drone-id", required=True, help="Identyfikator drona")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="Plik CSV z kolumnami lon,lat[,alt]")
    src.add_argument("--waypoints", help="Punkty inline 'lon,lat;lon,lat[;...]'")
    src.add_argument("--random-walk", nargs=2, type=float, metavar=("LAT", "LON"), help="Losowy spacer wokół LAT LON")
    p.add_argument("--alt", type=float, default=120.0, help="Domyślna wysokość, gdy brak w danych (m)")
    p.add_argument("--interval", type=float, default=1.0, help="Odstęp między punktami (s)")
    p.add_argument("--repeat", action="store_true", help="Pętla po zakończeniu trasy")
    p.add_argument("--noise-m", type=float, default=0.0, help="Szum pozycji (metry)")
    p.add_argument("--battery-start", type=float, default=95.0, help="Początkowy poziom baterii (%)")
    p.add_argument("--battery-drain-per-tick", type=float, default=0.3, help="Spadek baterii na punkt (%)")
    p.add_argument("--ignore-battery", action="store_true", help="Ignoruj rozładowanie baterii")
    p.add_argument("--yaw", type=float, default=180.0, help="Początkowy kurs (deg)")
    p.add_argument("--yaw-per-tick", type=float, default=3.0, help="Zmiana kursu na punkt (deg)")
    p.add_argument("--roll", type=float, default=0.0, help="Roll (deg)")
    p.add_argument("--pitch", type=float, default=0.0, help="Pitch (deg)")
    p.add_argument("--timeout", type=float, default=5.0, help="Timeout żądania (s)")
    p.add_argument("--auth-header", help='Niestandardowy nagłówek auth, np. "Authorization: Bearer XYZ"')
    p.add_argument("--insecure", action="store_true", help="Nie weryfikuj SSL (np. testowe https)")
    p.add_argument("--step-m", type=float, default=10.0, help="Długość kroku dla random-walk (m)")
    args = p.parse_args()
    run(args)
