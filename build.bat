@echo off
REM P2P File Sharing - Build Script
REM Builds both Tracker.exe and Peer.exe with PyInstaller

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   P2P FILE SHARING - BUILD SCRIPT
echo ============================================================
echo.

REM Set working directory
cd /d "%~dp0"

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.7+ and add it to your PATH
    pause
    exit /b 1
)

REM Check if PyInstaller is installed
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [!] PyInstaller not found. Installing...
    pip install pyinstaller>=6.0.0
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller
        pause
        exit /b 1
    )
)

echo [*] Configuration:
echo     Working Directory: %cd%
echo     Python: %python%
echo.

REM Check if required files exist
if not exist "tracker.py" (
    echo [ERROR] tracker.py not found!
    pause
    exit /b 1
)

if not exist "peer.py" (
    echo [ERROR] peer.py not found!
    pause
    exit /b 1
)

if not exist "config.ini" (
    echo [ERROR] config.ini not found!
    pause
    exit /b 1
)

echo [✓] All source files found
echo.

REM Clean old builds
echo [*] Cleaning old builds...
if exist "build" rmdir /s /q "build" >nul 2>&1
if exist "dist" rmdir /s /q "dist" >nul 2>&1
if exist "__pycache__" rmdir /s /q "__pycache__" >nul 2>&1
echo [✓] Old builds cleaned
echo.

REM Build Tracker.exe
echo ============================================================
echo STEP 1: Building Tracker.exe (Server)
echo ============================================================
echo.

call PyInstaller --clean --onefile --console --name "Tracker" --add-data "config.ini:." tracker.py

if errorlevel 1 (
    echo.
    echo [ERROR] Tracker.exe build failed!
    pause
    exit /b 1
)

if not exist "dist\Tracker.exe" (
    echo [ERROR] Tracker.exe not created!
    pause
    exit /b 1
)

for /f "tokens=*" %%A in ('powershell -Command "(Get-Item 'dist\Tracker.exe').Length"') do set TRACKER_SIZE=%%A
echo [✓] Tracker.exe built successfully (%TRACKER_SIZE% bytes)
echo.

REM Build Peer.exe
echo ============================================================
echo STEP 2: Building Peer.exe (Client with GUI)
echo ============================================================
echo.

call PyInstaller --clean --onefile --windowed --name "Peer" --add-data "config.ini:." peer.py

if errorlevel 1 (
    echo.
    echo [ERROR] Peer.exe build failed!
    pause
    exit /b 1
)

if not exist "dist\Peer.exe" (
    echo [ERROR] Peer.exe not created!
    pause
    exit /b 1
)

for /f "tokens=*" %%A in ('powershell -Command "(Get-Item 'dist\Peer.exe').Length"') do set PEER_SIZE=%%A
echo [✓] Peer.exe built successfully (%PEER_SIZE% bytes)
echo.

REM Verify both executables
echo ============================================================
echo BUILD VERIFICATION
echo ============================================================
echo.

echo [*] Generated Executables:
powershell -Command "Get-ChildItem 'dist\*.exe' | Select-Object @{Name='Name';Expression={$_.Name}}, @{Name='Size (MB)';Expression={'{0:N2}' -f ($_.Length/1MB)}}, @{Name='Modified';Expression={$_.LastWriteTime}}"

echo.
echo [✓] config.ini embedded in both executables
echo.

REM Create deployment info
echo ============================================================
echo [✓] BUILD COMPLETE!
echo ============================================================
echo.

echo Next Steps:
echo.
echo 1. CONFIGURE NETWORK (in config.ini):
echo    - Set TRACKER_HOST to your tracker machine's IP
echo    - Command: ipconfig (look for IPv4 Address)
echo.
echo 2. DEPLOY TRACKER:
echo    - Copy dist\Tracker.exe to tracker machine
echo    - Run: Tracker.exe
echo.
echo 3. DEPLOY PEERS (on each client machine):
echo    - Copy dist\Peer.exe to each machine
echo    - Run: Peer.exe
echo.
echo Executables ready in: %cd%\dist\
echo.

pause
exit /b 0
