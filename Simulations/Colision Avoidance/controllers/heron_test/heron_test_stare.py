from controller import Robot
import math
import csv
import time

robot = Robot()
timestep = int(robot.getBasicTimeStep())

def save_trajectory_csv(filename="heron_trajectory.csv"):
    import csv

    with open(filename, mode="w", newline="") as f:
        writer = csv.writer(f)

        writer.writerow([
            "time",
            "robot_x", "robot_y", "robot_z",
            "yaw",
            "mode",
            "obstacle_type",
            "obstacle_x", "obstacle_y", "obstacle_z",
            "obstacle_sx", "obstacle_sy", "obstacle_sz",
            "target_x", "target_y", "target_z"
        ])

        ox, oy, oz = OBSTACLE["position"]
        sx, sy, sz = OBSTACLE.get("size", (0.0, 0.0, 0.0))

        for p in trajectory:
            writer.writerow([
                p["time"],
                p["x"], p["y"], p["z"],
                p["yaw"],
                p["mode"],
                OBSTACLE["type"],
                ox, oy, oz,
                sx, sy, sz,
                TARGET[0], TARGET[1], TARGET[2]
            ])
print("\n=== HERON AUTOPILOT — GPS + IMU/COMPASS + LIDAR AVOID ===")

# ===== MOTORS =====
left_motor = robot.getDevice("left_motor")
right_motor = robot.getDevice("right_motor")

left_motor.setPosition(float("inf"))
right_motor.setPosition(float("inf"))
left_motor.setVelocity(0.0)
right_motor.setVelocity(0.0)

# ===== SENSORS =====
def get_sensor(name):
    try:
        dev = robot.getDevice(name)
        dev.enable(timestep)
        print(f"[OK] Sensor enabled: {name}")
        return dev
    except Exception:
        print(f"[ERR] Sensor not found: {name}")
        return None

gps = get_sensor("gps")
compass = get_sensor("compass")
imu = get_sensor("inertial unit")
lidar = get_sensor("lidar")

if lidar:
    try:
        print("Lidar horizontal resolution:", lidar.getHorizontalResolution())
        print("Lidar FOV (rad):", lidar.getFov())
    except Exception:
        pass

# ===== TARGET (ustaw swój punkt docelowy) =====
# Webots GPS daje [x, y, z]. Zwykle nawigacja jest po (x, y).
TARGET = [0.0, -9.2393, 0.710646]

#START_POS = [0.178416, 7.61522, 0.655721]
START_POS = [0.255964, 11.1569, 0.202583]


OBSTACLE = {
    "type": "barrel",
    "position": (0.379553, 0.0437297, 0.76)
}


trajectory = []   # lista punktów trajektorii

# =========================
# AUTOPILOT SETTINGS
# =========================
BASE_SPEED = 6.0          # base speed
TURN_GAIN = 2.5           # steering P gain
MAX_SPEED = 9.0           # motor saturation
SLOW_DIST = 3.0           # slow down when closer than this
STOP_DIST = 0.8           # considered arrived within this radius

OBSTACLE_DIST = 2.0       # avoid trigger (front)
AVOID_TURN = 1.5          # fixed avoid steering magnitude

# --- ESCAPE/CONTACT ---
ESCAPE_TRIGGER = 2.0      # very close: likely contact / too close
ESCAPE_TIME = 1.2         # seconds of escape action
ESCAPE_BACK = -3.5        # reverse speed
ESCAPE_SPIN = 3.0         # spin magnitude during escape

# --- RECOVERY (EDGE-GUARD) ---
RECOVER_TIME = 2.0        # seconds of guarded return-to-target
EDGE_TRIGGER = 2.2        # if edge sees obstacle closer than this -> block unwinding into it
EDGE_W_FRAC = 0.06        # width of edge sector as fraction of lidar samples
EDGE_BOUNCE_TURN = 0.35   # gentle bounce away from obstacle edge
MAX_RECOVER_TURN = 0.8    # limit steering during recover (reduce oscillations)


# =============================
# HELPERS
# =============================
def normalize_angle(a):
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a

def bearing_to_target(current_pos, target_pos):
    dx = target_pos[0] - current_pos[0]
    dy = target_pos[1] - current_pos[1]
    return math.atan2(dy, dx)

def distance_xy(a, b):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    return math.sqrt(dx*dx + dy*dy)

def get_yaw(imu, compass):
    """
    Prefer IMU yaw. Jeśli IMU brak, próbuj oszacować yaw z kompasu.
    Zwraca yaw w radianach (–pi..pi) albo None.
    """
    if imu:
        rpy = imu.getRollPitchYaw()
        return rpy[2]

    # Fallback kompas: w Webots kompas daje wektor kierunku północy w ramie robota.
    # Typowe wyznaczenie yaw: atan2(north_x, north_z) lub podobne zależnie od osi.
    # Najczęściej w Webots: atan2(c[0], c[2]) daje yaw w płaszczyźnie XZ.
    if compass:
        c = compass.getValues()
        # Uwaga: jeśli u Ciebie osie są inne, może wymagać zamiany znaków.
        yaw = math.atan2(c[0], c[2])
        return yaw

    return None

def clamp(v, lo, hi):
    return max(lo, min(hi, v))



def autopilot_step(
    gps, compass, imu, lidar,
    left_motor, right_motor,
    target_pos,
    dt
):
    global AP_MODE, AVOID_SIDE, AVOID_HOLD, ESCAPE_HOLD

    # --- wymagane minimum ---
    if not gps:
        left_motor.setVelocity(0.0)
        right_motor.setVelocity(0.0)
        return {"status": "NO_GPS"}

    pos = gps.getValues()
    yaw = get_yaw(imu, compass)
    if yaw is None:
        left_motor.setVelocity(0.0)
        right_motor.setVelocity(0.0)
        return {"status": "NO_YAW", "pos": pos}

    # --- nawigacja do celu ---
    dist = distance_xy(pos, target_pos)
    if dist <= STOP_DIST:
        left_motor.setVelocity(0.0)
        right_motor.setVelocity(0.0)
        AP_MODE = "GO"
        AVOID_SIDE = None
        AVOID_HOLD = 0.0
        ESCAPE_HOLD = 0.0
        save_trajectory_csv("heron_trajectory.csv")
        print("Trajektoria zapisana do heron_trajectory.csv")
        return {"status": "ARRIVED", "dist": dist}

    desired_yaw = bearing_to_target(pos, target_pos)
    yaw_error = normalize_angle(desired_yaw - yaw)

    # prędkość bazowa z rampą przy celu
    speed_scale = 1.0
    if dist < SLOW_DIST:
        speed_scale = clamp(dist / SLOW_DIST, 0.3, 1.0)
    base = BASE_SPEED * speed_scale

    # sterowanie kursem (P)
    turn_cmd = TURN_GAIN * yaw_error

    # --- lidar sektory ---
    front_min = float("inf")
    left_min = float("inf")
    right_min = float("inf")
    if lidar:
        ranges = lidar.getRangeImage()
        n = len(ranges)
        if n > 10:
            mid = n // 2

            # front szerszy niż wcześniej (mniej “wąskiego tunelu”)
            front_w = max(5, int(0.08 * n))

            # sektory boczne: bardziej “na przód” niż na tył
            right_a = int(0.30 * n)
            right_b = int(0.45 * n)
            left_a  = int(0.55 * n)
            left_b  = int(0.70 * n)

            front_sector = ranges[mid - front_w: mid + front_w + 1]
            left_sector  = ranges[left_a:left_b]
            right_sector = ranges[right_a:right_b]

            front_min = min(front_sector) if front_sector else float("inf")
            left_min  = min(left_sector) if left_sector else float("inf")
            right_min = min(right_sector) if right_sector else float("inf")

    # progi: “zobacz przeszkodę” vs “awaryjnie za blisko”
    AVOID_TRIGGER = OBSTACLE_DIST          # np. 2.0
    ESCAPE_TRIGGER = 1.0                   # bardzo blisko – zwykle kolizja / kontakt

    # =========================
    # STATE MACHINE
    # =========================

    # 1) ESCAPE: jak za blisko, cofnij i skręć zdecydowanie (bez oscylacji)
    if front_min < ESCAPE_TRIGGER:
        AP_MODE = "ESCAPE"
        if ESCAPE_HOLD <= 0.0:
            ESCAPE_HOLD = 1.2  # sekundy wykonywania ucieczki
            # wybierz stronę na podstawie wolniejszej przestrzeni i ZABLOKUJ
            AVOID_SIDE = "LEFT" if left_min > right_min else "RIGHT"

    if AP_MODE == "ESCAPE":
        ESCAPE_HOLD -= dt

        # cofanie + skręt
        back = -3.5  # prędkość cofania
        spin = 3.0   # prędkość skrętu w miejscu

        if AVOID_SIDE == "LEFT":
            left_speed = back - spin
            right_speed = back + spin
        else:
            left_speed = back + spin
            right_speed = back - spin

        left_motor.setVelocity(clamp(left_speed, -MAX_SPEED, MAX_SPEED))
        right_motor.setVelocity(clamp(right_speed, -MAX_SPEED, MAX_SPEED))

        if ESCAPE_HOLD <= 0.0:
            AP_MODE = "AVOID"
            AVOID_HOLD = 3.0  # po ucieczce trzymaj omijanie przez chwilę

        return {
            "status": "ESCAPE",
            "front": front_min, "left": left_min, "right": right_min,
            "side": AVOID_SIDE
        }

    # 2) AVOID: jeśli przeszkoda w zasięgu, wybierz stronę i TRZYMAJ ją
    if front_min < AVOID_TRIGGER:
        if AP_MODE != "AVOID":
            AP_MODE = "AVOID"
            AVOID_HOLD = 3.0  # sekundy blokady decyzji
            AVOID_SIDE = "LEFT" if left_min > right_min else "RIGHT"

    if AP_MODE == "AVOID":
        AVOID_HOLD -= dt

        # redukcja prędkości do omijania (żeby nie “wciskać się” w obiekt)
        base_avoid = min(base, 3.0)
        # stały skręt w zablokowaną stronę + lekki wpływ błędu kursu
        avoid_turn = AVOID_TURN
        avoid_turn += 0.3 * (TURN_GAIN * yaw_error)  # niech nadal “pamięta” o celu

        if AVOID_SIDE == "LEFT":
            turn_cmd = +avoid_turn
        else:
            turn_cmd = -avoid_turn

        # jeśli przód się oczyścił i skończył się hold, wróć do GO
        if (front_min > AVOID_TRIGGER * 1.2) and (AVOID_HOLD <= 0.0):
            AP_MODE = "GO"
            AVOID_SIDE = None
            AVOID_HOLD = 0.0
            # przejdź dalej do GO (czyli normalne sterowanie)
        else:
            left_speed = base_avoid - turn_cmd
            right_speed = base_avoid + turn_cmd
            left_motor.setVelocity(clamp(left_speed, -MAX_SPEED, MAX_SPEED))
            right_motor.setVelocity(clamp(right_speed, -MAX_SPEED, MAX_SPEED))

            return {
                "status": "AVOID",
                "front": front_min, "left": left_min, "right": right_min,
                "side": AVOID_SIDE, "hold": AVOID_HOLD
            }

    # 3) GO: standardowe sterowanie na cel (gdy nie omijamy)
    left_speed = base - turn_cmd
    right_speed = base + turn_cmd

    left_motor.setVelocity(clamp(left_speed, -MAX_SPEED, MAX_SPEED))
    right_motor.setVelocity(clamp(right_speed, -MAX_SPEED, MAX_SPEED))

    return {
        "status": "GO",
        "dist": dist,
        "yaw_error": yaw_error,
        "front": front_min, "left": left_min, "right": right_min
    }


# =============================
# MAIN LOOP
# =============================
print(f"\nAutopilot aktywny — płynię do celu: x={TARGET[0]:.2f}, y={TARGET[1]:.2f}\n")

while robot.step(timestep) != -1:
    dt = timestep / 1000.0
    info = autopilot_step(
        gps=gps, compass=compass, imu=imu, lidar=lidar,
        left_motor=left_motor, right_motor=right_motor,
        target_pos=TARGET,
        dt=dt
    )

    # --- SENSOR PRINT TIMER ---
    time_acc += timestep / 1000.0
    if time_acc >= PRINT_INTERVAL:
        print("\n--- AUTOPILOT / SENSOR DATA ---")

        if gps:
            p = gps.getValues()
            print(f"GPS: x={p[0]:.2f}, y={p[1]:.2f}, z={p[2]:.2f}")

        if compass:
            c = compass.getValues()
            print(f"Compass: [{c[0]:.2f}, {c[1]:.2f}, {c[2]:.2f}]")

        if imu:
            rpy = imu.getRollPitchYaw()
            print(f"IMU: roll={rpy[0]:.2f}, pitch={rpy[1]:.2f}, yaw={rpy[2]:.2f}")

        if lidar:
            data = lidar.getRangeImage()
            if data:
                min_val = min(data)
                min_idx = data.index(min_val)
                print(f"Lidar min: idx={min_idx}, dist={min_val:.2f}, n={len(data)}")

        if gps and imu:
            pos = gps.getValues()
            yaw = imu.getRollPitchYaw()[2]

            trajectory.append({
                "time": robot.getTime(),
                "x": pos[0],
                "y": pos[1],
                "z": pos[2],
                "yaw": yaw,
                "mode": info.get("status")
            })


        # autopilot info
        print(f"AP: status={info.get('status')}, dist={info.get('dist', float('nan')):.2f}, "
              f"yaw_err={info.get('yaw_error', float('nan')):.2f}, "
              f"vL={info.get('vL', 0.0):.2f}, vR={info.get('vR', 0.0):.2f}")

        if info.get("avoid") is not None:
            mode, front_min, left_min, right_min = info["avoid"]
            print(f"AP avoid: {mode} | front={front_min:.2f} left={left_min:.2f} right={right_min:.2f}")

        print("-----------------------------\n")
        time_acc = 0.0
