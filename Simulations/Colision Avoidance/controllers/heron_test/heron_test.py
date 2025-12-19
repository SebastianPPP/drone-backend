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

# Keep obstacle meta (optional) for CSV
OBSTACLE = {
    "type": "brick_block",
    "position": (0.379553, 0.0437297, 0.76),
    "size": (6.0, 6.0, 2.0)
}

trajectory = []   # lista punktów trajektorii

# =========================
# AUTOPILOT SETTINGS
# =========================
BASE_SPEED = 5.0          # base speed
TURN_GAIN = 2.5           # steering P gain
MAX_SPEED = 9.0           # motor saturation
SLOW_DIST = 3.0           # slow down when closer than this
STOP_DIST = 0.8           # considered arrived within this radius

# Avoid / Escape thresholds
OBSTACLE_DIST = 3.8       # earlier trigger helps with big obstacle
ESCAPE_TRIGGER = 1.2       # "contact/too close" threshold (consistent - not overwritten)

# Stronger avoid behavior (your issue: too weak)
AVOID_HOLD_TIME = 4.0
AVOID_BASE_SPEED = 4.0     # slower in avoid => more time to turn before hitting
AVOID_TURN = 4.0           # stronger fixed turn than 1.5

# Escape behavior
ESCAPE_TIME = 1.2
ESCAPE_BACK = -3.5
ESCAPE_SPIN = 3.2          # slightly stronger spin

# Recovery edge-guard
RECOVER_TIME = 1.0
EDGE_TRIGGER = 4.2
EDGE_W_FRAC = 0.10
EDGE_BOUNCE_TURN = 0.95
MAX_RECOVER_TURN = 1.6

# =========================
# PRINT TIMER
# =========================
PRINT_INTERVAL = 0.5
time_acc = 0.0

# =========================
# GLOBAL STATE (IMPORTANT!)
# =========================
AP_MODE = "GO"          # "GO", "AVOID", "ESCAPE", "RECOVER"
AVOID_SIDE = None       # "LEFT" or "RIGHT"
AVOID_HOLD = 0.0
ESCAPE_HOLD = 0.0
RECOVER_HOLD = 0.0
LAST_AVOID_SIDE = None

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


# =========================
# AUTOPILOT STEP
# =========================

def autopilot_step(
    gps, compass, imu, lidar,
    left_motor, right_motor,
    target_pos,
    dt
):
    global AP_MODE, AVOID_SIDE, AVOID_HOLD, ESCAPE_HOLD, RECOVER_HOLD

    # --- wymagane minimum ---
    if not gps:
        left_motor.setVelocity(0.0)
        right_motor.setVelocity(0.0)
        return {"status": "NO_GPS", "vL": 0.0, "vR": 0.0}

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

            front_w = max(5, int(0.10 * n))   # slightly wider
            right_a = int(0.28 * n)
            right_b = int(0.46 * n)
            left_a  = int(0.54 * n)
            left_b  = int(0.72 * n)

            front_sector = ranges[mid - front_w: mid + front_w + 1]
            left_sector  = ranges[left_a:left_b]
            right_sector = ranges[right_a:right_b]

            front_min = min(front_sector) if front_sector else float("inf")
            left_min  = min(left_sector) if left_sector else float("inf")
            right_min = min(right_sector) if right_sector else float("inf")

            edge_w = max(3, int(EDGE_W_FRAC * n))
            right_edge_min = min(ranges[0:edge_w]) if edge_w > 0 else float("inf")
            left_edge_min = min(ranges[n-edge_w:n]) if edge_w > 0 else float("inf")

    
    # =========================
    # STATE MACHINE
    # =========================

    # 1) ESCAPE if too close ahead
    if front_min < ESCAPE_TRIGGER:
        AP_MODE = "ESCAPE"
        if ESCAPE_HOLD <= 0.0:
            ESCAPE_HOLD = ESCAPE_TIME
            AVOID_SIDE = "LEFT" if left_min > right_min else "RIGHT"

    if AP_MODE == "ESCAPE":
        ESCAPE_HOLD -= dt

        back = ESCAPE_BACK
        spin = ESCAPE_SPIN
        if AVOID_SIDE == "LEFT":
            vL = back - spin
            vR = back + spin
        else:
            vL = back + spin
            vR = back - spin

        vL = clamp(vL, -MAX_SPEED, MAX_SPEED)
        vR = clamp(vR, -MAX_SPEED, MAX_SPEED)
        left_motor.setVelocity(vL)
        right_motor.setVelocity(vR)

        if ESCAPE_HOLD <= 0.0:
            AP_MODE = "AVOID"
            AVOID_HOLD = AVOID_HOLD_TIME

        return {
            "status": "ESCAPE",
            "dist": dist, "yaw_error": yaw_error,
            "front": front_min, "left": left_min, "right": right_min,
            "left_edge": left_edge_min, "right_edge": right_edge_min,
            "vL": vL, "vR": vR
        }

    # 2) Trigger AVOID when obstacle seen in front
    if front_min < OBSTACLE_DIST:
        if AP_MODE != "AVOID":
            AP_MODE = "AVOID"
            AVOID_HOLD = AVOID_HOLD_TIME
            AVOID_SIDE = "LEFT" if left_min > right_min else "RIGHT"

    # 3) AVOID behavior (STRONGER + SLOWER)
    if AP_MODE == "AVOID":
        AVOID_HOLD -= dt

        # stronger: keep low forward speed, strong turn
        base_avoid = min(base, AVOID_BASE_SPEED)

        # optionally increase turn when very close to obstacle
        # (front_min near ESCAPE_TRIGGER => turn stronger)
        proximity_boost = 0.0
        if front_min < (OBSTACLE_DIST * 0.7):
            proximity_boost = 0.8

        avoid_turn = AVOID_TURN + proximity_boost

        # keep a small bias to still "remember" target direction (but not dominate)
        avoid_turn += 0.15 * clamp(turn_cmd, -2.0, 2.0)

        turn_use = +avoid_turn if AVOID_SIDE == "LEFT" else -avoid_turn

        vL = clamp(base_avoid - turn_use, -MAX_SPEED, MAX_SPEED)
        vR = clamp(base_avoid + turn_use, -MAX_SPEED, MAX_SPEED)

        left_motor.setVelocity(vL)
        right_motor.setVelocity(vR)

        # exit avoid -> RECOVER (not directly GO)
        if (front_min > OBSTACLE_DIST * 1.25) and (AVOID_HOLD <= 0.0):
            AP_MODE = "RECOVER"
            RECOVER_HOLD = RECOVER_TIME
            AVOID_SIDE = None
            AVOID_HOLD = 0.0

        return {
            "status": "AVOID",
            "dist": dist, "yaw_error": yaw_error,
            "front": front_min, "left": left_min, "right": right_min,
            "left_edge": left_edge_min, "right_edge": right_edge_min,
            "vL": vL, "vR": vR
        }

    # 4) RECOVER: return-to-target but don't unwind into obstacle edges
    if AP_MODE == "RECOVER":
        RECOVER_HOLD -= dt

        # Slightly slower forward speed to let yaw change faster without hitting
        base_rec = min(base, 3.0)

        # Stronger return-to-target steering (scaled up vs GO)
        recover_turn = 1.35 * (TURN_GAIN * yaw_error)
        recover_turn = clamp(recover_turn, -MAX_RECOVER_TURN, MAX_RECOVER_TURN)

        turning_left = recover_turn > 0.0
        turning_right = recover_turn < 0.0

        # Edge guard: if turning into obstacle edge, bounce away more decisively
        if turning_left and (left_edge_min < EDGE_TRIGGER):
            recover_turn = -EDGE_BOUNCE_TURN
        elif turning_right and (right_edge_min < EDGE_TRIGGER):
            recover_turn = +EDGE_BOUNCE_TURN

        vL = clamp(base_rec - recover_turn, -MAX_SPEED, MAX_SPEED)
        vR = clamp(base_rec + recover_turn, -MAX_SPEED, MAX_SPEED)

        left_motor.setVelocity(vL)
        right_motor.setVelocity(vR)

        # Exit RECOVER only when:
        # - timer elapsed AND
        # - front is clear with margin AND
        # - edges are not "too close" anymore
        if (RECOVER_HOLD <= 0.0) and (front_min > OBSTACLE_DIST * 1.2) and (left_edge_min > EDGE_TRIGGER) and (right_edge_min > EDGE_TRIGGER):
            AP_MODE = "GO"

        return {
            "status": "RECOVER",
            "dist": dist, "yaw_error": yaw_error,
            "front": front_min, "left": left_min, "right": right_min,
            "left_edge": left_edge_min, "right_edge": right_edge_min,
            "vL": vL, "vR": vR
        }
    # 5) GO
    vL = clamp(base - turn_cmd, -MAX_SPEED, MAX_SPEED)
    vR = clamp(base + turn_cmd, -MAX_SPEED, MAX_SPEED)
    left_motor.setVelocity(vL)
    right_motor.setVelocity(vR)

    return {
        "status": "GO",
        "dist": dist, "yaw_error": yaw_error,
        "front": front_min, "left": left_min, "right": right_min,
        "left_edge": left_edge_min, "right_edge": right_edge_min,
        "vL": vL, "vR": vR
    }


# =========================
# MAIN LOOP
# =========================
print(f"\nAutopilot active — target: x={TARGET[0]:.2f}, y={TARGET[1]:.2f}\n")

saved = False

while robot.step(timestep) != -1:
    dt = timestep / 1000.0

    info = autopilot_step(
        gps=gps, compass=compass, imu=imu, lidar=lidar,
        left_motor=left_motor, right_motor=right_motor,
        target_pos=TARGET,
        dt=dt
    )

    # log trajectory every step
    if gps and imu:
        p = gps.getValues()
        yaw = imu.getRollPitchYaw()[2]
        trajectory.append({
            "time": robot.getTime(),
            "x": p[0], "y": p[1], "z": p[2],
            "yaw": yaw,
            "mode": info.get("status")
        })

    # save once on arrival
    if (info.get("status") == "ARRIVED") and not saved:
        save_trajectory_csv("heron_trajectory.csv")
        print("[OK] Trajectory saved to heron_trajectory.csv")
        saved = True

    # periodic print
    time_acc += dt
    if time_acc >= PRINT_INTERVAL:
        print(
            f"AP: status={info.get('status')}, "
            f"dist={info.get('dist', float('nan')):.2f}, "
            f"yaw_err={info.get('yaw_error', float('nan')):.2f}, "
            f"front={info.get('front', float('nan')):.2f}, "
            f"edgeL={info.get('left_edge', float('nan')):.2f}, "
            f"edgeR={info.get('right_edge', float('nan')):.2f}, "
            f"vL={info.get('vL', 0.0):.2f}, vR={info.get('vR', 0.0):.2f}"
        )
        print("-----------------------------\n")
        time_acc = 0.0