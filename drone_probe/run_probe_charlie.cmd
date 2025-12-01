@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem === Run from this script directory ===
cd /d "%~dp0"

rem --------- DOMYŚLNE USTAWIENIA (możesz zmienić) ----------
set "SERVER=http://localhost:5000"
set "DRONE=charlie"
set "CSV=telemetry_sample2.csv"
set "INTERVAL=1"
set "REPEAT=1"                 rem 1=--repeat, 0=bez powtarzania
set "NOISE_M=0"               rem szum w metrach
set "BATTERY_START=95"
set "BATTERY_DRAIN=0.3"       rem % na punkt
set "IGNORE_BATTERY=0"        rem 1=ignoruj rozładowanie
set "YAW=180"
set "YAW_PER_TICK=3"
set "ROLL=0"
set "PITCH=0"
set "TIMEOUT=5"
set "AUTH_HEADER="            rem np. Authorization: Bearer XYZ
set "INSECURE=0"              rem 1=nie weryfikuj SSL (https testowe)

rem --------- PARSOWANIE NAZWANYCH ARGUMENTÓW ----------
rem Użycie: run_probe.cmd DRONE=alpha SERVER=http://... BATTERY_START=80 ...
for %%A in (%*) do (
  for /f "tokens=1,2 delims==" %%K in ("%%~A") do (
    if /i "%%~K"==SERVER           set "SERVER=%%~L"
    if /i "%%~K"==DRONE            set "DRONE=%%~L"
    if /i "%%~K"==CSV              set "CSV=%%~L"
    if /i "%%~K"==INTERVAL         set "INTERVAL=%%~L"
    if /i "%%~K"==REPEAT           set "REPEAT=%%~L"
    if /i "%%~K"==NOISE_M          set "NOISE_M=%%~L"
    if /i "%%~K"==BATTERY_START    set "BATTERY_START=%%~L"
    if /i "%%~K"==BATTERY_DRAIN    set "BATTERY_DRAIN=%%~L"
    if /i "%%~K"==IGNORE_BATTERY   set "IGNORE_BATTERY=%%~L"
    if /i "%%~K"==YAW              set "YAW=%%~L"
    if /i "%%~K"==YAW_PER_TICK     set "YAW_PER_TICK=%%~L"
    if /i "%%~K"==ROLL             set "ROLL=%%~L"
    if /i "%%~K"==PITCH            set "PITCH=%%~L"
    if /i "%%~K"==TIMEOUT          set "TIMEOUT=%%~L"
    if /i "%%~K"==AUTH_HEADER      set "AUTH_HEADER=%%~L"
    if /i "%%~K"==INSECURE         set "INSECURE=%%~L"
  )
)

rem --------- FLAGI OPCYJNE ----------
set "REPEAT_FLAG="
if "%REPEAT%"=="1" set "REPEAT_FLAG=--repeat"

set "IGNORE_FLAG="
if "%IGNORE_BATTERY%"=="1" set "IGNORE_FLAG=--ignore-battery"

set "INSECURE_FLAG="
if "%INSECURE%"=="1" set "INSECURE_FLAG=--insecure"

set "AUTH_FLAG="
if not "%AUTH_HEADER%"=="" set "AUTH_FLAG=--auth-header "%AUTH_HEADER%""

rem --------- SPRAWDZENIA ----------
if not exist "%CSV%" (
  echo [ERR] Nie znaleziono pliku CSV: %CSV%
  echo       Umiesc go obok tego pliku lub podaj CSV=pelna_sciezka.csv
  exit /b 1
)

rem --------- URUCHOMIENIE PROBE.PY ----------
echo [RUN] python probe.py ^
 --server "%SERVER%" --drone-id "%DRONE%" ^
 --csv "%CSV%" --interval %INTERVAL% ^
 --noise-m %NOISE_M% --battery-start %BATTERY_START% --battery-drain-per-tick %BATTERY_DRAIN% ^
 --yaw %YAW% --yaw-per-tick %YAW_PER_TICK% --roll %ROLL% --pitch %PITCH% --timeout %TIMEOUT% ^
 %REPEAT_FLAG% %IGNORE_FLAG% %INSECURE_FLAG% %AUTH_FLAG%
echo.

python probe.py --server "%SERVER%" --drone-id "%DRONE%" ^
 --csv "%CSV%" --interval %INTERVAL% ^
 --noise-m %NOISE_M% --battery-start %BATTERY_START% --battery-drain-per-tick %BATTERY_DRAIN% ^
 --yaw %YAW% --yaw-per-tick %YAW_PER_TICK% --roll %ROLL% --pitch %PITCH% --timeout %TIMEOUT% ^
 %REPEAT_FLAG% %IGNORE_FLAG% %INSECURE_FLAG% %AUTH_FLAG%

endlocal
