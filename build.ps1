# P2P File Sharing - Build Script (PowerShell Version)
# Builds both Tracker.exe and Peer.exe with PyInstaller

param(
    [switch]$SkipClean = $false,
    [switch]$SkipVerify = $false
)

$ErrorActionPreference = "Stop"
$WarningPreference = "Continue"

# Colors
$colors = @{
    Success = "Green"
    Error = "Red"
    Info = "Cyan"
    Warning = "Yellow"
}

function Write-Status {
    param([string]$Message, [string]$Type = "Info")
    $color = $colors[$Type]
    
    if ($Type -eq "Success") {
        Write-Host "[✓] $Message" -ForegroundColor $color
    } elseif ($Type -eq "Error") {
        Write-Host "[✗] $Message" -ForegroundColor $color
    } else {
        Write-Host "[*] $Message" -ForegroundColor $color
    }
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

# Header
Write-Host ""
Write-Section "P2P FILE SHARING - BUILD SCRIPT"

# Get working directory
$workingDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $workingDir
Write-Status "Working Directory: $workingDir"

# Check Python installation
try {
    $pythonVersion = python --version 2>&1 | ForEach-Object { $_ }
    Write-Status "Found $pythonVersion" "Success"
} catch {
    Write-Status "Python is not installed or not in PATH" "Error"
    Write-Host "Please install Python 3.7+ and add it to your PATH" -ForegroundColor Red
    exit 1
}

# Check PyInstaller
try {
    pip show pyinstaller | Out-Null
    Write-Status "PyInstaller is installed" "Success"
} catch {
    Write-Status "PyInstaller not found. Installing..." "Warning"
    pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        Write-Status "Failed to install PyInstaller" "Error"
        exit 1
    }
    Write-Status "PyInstaller installed successfully" "Success"
}

Write-Host ""

# Verify required files
$requiredFiles = @("tracker.py", "peer.py", "config.ini")
$allFilesExist = $true

foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Status "Found: $file" "Success"
    } else {
        Write-Status "Missing: $file" "Error"
        $allFilesExist = $false
    }
}

if (-not $allFilesExist) {
    exit 1
}

Write-Host ""

# Clean old builds
if (-not $SkipClean) {
    Write-Status "Cleaning old builds..."
    $cleanDirs = @("build", "__pycache__")
    
    foreach ($dir in $cleanDirs) {
        if (Test-Path $dir) {
            Remove-Item -Path $dir -Recurse -Force -ErrorAction SilentlyContinue
            Write-Status "Removed $dir"
        }
    }
    
    # Rename old dist if it exists
    if (Test-Path "dist") {
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backupName = "dist_backup_$timestamp"
        Rename-Item -Path "dist" -NewName $backupName -ErrorAction SilentlyContinue
        Write-Status "Backed up old dist to $backupName"
    }
    
    Write-Status "Build cleanup complete" "Success"
    Write-Host ""
}

# Build Tracker.exe
Write-Section "STEP 1: Building Tracker.exe (Server)"

Write-Status "Starting PyInstaller..."
$trackerBuildOutput = & PyInstaller --clean --onefile --console --name "Tracker" --add-data "config.ini:." tracker.py 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Status "Tracker.exe build failed!" "Error"
    Write-Host $trackerBuildOutput
    exit 1
}

if (-not (Test-Path "dist\Tracker.exe")) {
    Write-Status "Tracker.exe was not created!" "Error"
    exit 1
}

$trackerSize = (Get-Item "dist\Tracker.exe").Length
$trackerSizeMB = [math]::Round($trackerSize / 1MB, 2)
Write-Status "Tracker.exe built successfully ($trackerSizeMB MB)" "Success"
Write-Host ""

# Build Peer.exe
Write-Section "STEP 2: Building Peer.exe (Client with GUI)"

Write-Status "Starting PyInstaller..."
$peerBuildOutput = & PyInstaller --clean --onefile --windowed --name "Peer" --add-data "config.ini:." peer.py 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Status "Peer.exe build failed!" "Error"
    Write-Host $peerBuildOutput
    exit 1
}

if (-not (Test-Path "dist\Peer.exe")) {
    Write-Status "Peer.exe was not created!" "Error"
    exit 1
}

$peerSize = (Get-Item "dist\Peer.exe").Length
$peerSizeMB = [math]::Round($peerSize / 1MB, 2)
Write-Status "Peer.exe built successfully ($peerSizeMB MB)" "Success"
Write-Host ""

# Verify executables
Write-Section "BUILD VERIFICATION"

$exeFiles = Get-ChildItem "dist\*.exe"

if ($exeFiles.Count -eq 2) {
    Write-Status "Both executables created successfully" "Success"
    Write-Host ""
    Write-Host "Generated Executables:" -ForegroundColor Cyan
    Write-Host ""
    
    $exeFiles | ForEach-Object {
        $sizeKB = [math]::Round($_.Length / 1KB, 1)
        $modTime = $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        Write-Host "  ✓ $($_.Name) - $sizeKB KB - $modTime" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Status "config.ini embedded in both executables" "Success"
} else {
    Write-Status "Expected 2 executables, found $($exeFiles.Count)" "Error"
    exit 1
}

Write-Host ""

# Success summary
Write-Section "✓ BUILD COMPLETE!"

Write-Host ""
Write-Host "📋 Next Steps:" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. CONFIGURE NETWORK (edit config.ini):" -ForegroundColor Yellow
Write-Host "   - Set TRACKER_HOST to your tracker machine's IP"
Write-Host "   - Run: ipconfig" -ForegroundColor Gray
Write-Host "   - Look for: IPv4 Address" -ForegroundColor Gray
Write-Host ""
Write-Host "2. DEPLOY TRACKER (on server machine):" -ForegroundColor Yellow
Write-Host "   - Copy dist\Tracker.exe" -ForegroundColor Gray
Write-Host "   - Run: Tracker.exe" -ForegroundColor Gray
Write-Host ""
Write-Host "3. DEPLOY PEERS (on each client machine):" -ForegroundColor Yellow
Write-Host "   - Copy dist\Peer.exe" -ForegroundColor Gray
Write-Host "   - Run: Peer.exe" -ForegroundColor Gray
Write-Host ""
Write-Host "📁 Output Location:" -ForegroundColor Cyan
Write-Host "   $workingDir\dist\" -ForegroundColor Green
Write-Host ""

# Offer to open explorer
$response = Read-Host "Open dist folder in Explorer? (Y/N)"
if ($response -eq "Y" -or $response -eq "y") {
    Invoke-Item "dist\"
}

Write-Host ""
exit 0
