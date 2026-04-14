# P2P File Sharing

A simple peer-to-peer file sharing application. Share files directly between computers on the same network using a central tracker.

## How it Works

- **Tracker** - Central server that keeps track of which files are on which peers
- **Peers** - Client applications that can upload and download files from each other

## Requirements

- Python 3.7+
- Tkinter (comes with Python on Windows/Mac, install with `apt-get install python3-tk` on Linux)

## Setup

### 1. Install Dependencies

```bash
pip install pyinstaller
```

### 2. Configure the Network

Edit `config.ini` and set the tracker IP:

```ini
[Network]
TRACKER_HOST=<tracker_ip_address>

[Ports]
TRACKER_PORT=5000
STARTING_PEER_PORT=5001

[Download]
DOWNLOAD_DIR=./downloads/

[Performance]
CHUNK_SIZE=65536
MAX_CONCURRENT_DOWNLOADS=3
```

To find your tracker's IP:
- **Windows:** Open Command Prompt and run `ipconfig` (look for IPv4 Address)
- **Linux/Mac:** Run `ifconfig` or `hostname -I`

### 3. Start the Tracker

Run on the machine that will act as tracker:

```bash
python tracker.py
```

You should see:
```
Tracker listening on [IP]:5000
```

### 4. Start Peer Clients

On each machine that will share files:

```bash
python peer.py
```

A window will open with the file sharing interface.

## Using the GUI

### Main Window

**File List Section:**
- Shows all available files from peers on the network
- Click a file to select it

**Buttons:**

- **Add File** - Choose a file from your computer to share
- **Download** - Download the selected file from the list
- **Remove** - Stop sharing a file you added
- **Refresh** - Update the available files list

**Status Box:**
- Shows download progress and network activity
- Updates in real-time

### Workflow Example

1. Open `peer.py` on two computers (make sure they can reach the tracker)
2. On Computer A: Click "Add File" and select a file to share
3. On Computer B: Click "Refresh" and see the file from Computer A
4. On Computer B: Select the file and click "Download"
5. File downloads to `./downloads/` folder
6. Status box shows progress

## Troubleshooting

**Peers not seeing each other:**
- Check that both computers have correct `TRACKER_HOST` in config.ini
- Make sure firewall allows connections on ports 5000 and 5001+
- Verify tracker is running

**Downloads stuck:**
- Try clicking "Refresh" to reconnect
- Check status box for error messages
- Restart the peer application

**Files won't add:**
- Make sure file exists and isn't locked by another program
- Check write permissions in download folder

## Folders

- `downloads/` - Where downloaded files are saved
- `shared_files/` - Optional folder for files to share
