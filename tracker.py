#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2P File Sharing - Tracker Server
Maintains list of active peers and tracks which files they have
Central index for peer discovery
"""

import socket
import threading
import json
import time
from datetime import datetime
import configparser
from pathlib import Path
import sys

# Load configuration - works with both .py and .exe
config = configparser.ConfigParser()

# For PyInstaller .exe, get directory from sys.executable or current working directory
if getattr(sys, 'frozen', False):
    # Running as compiled .exe
    exe_dir = Path(sys.executable).parent
else:
    # Running as .py script
    exe_dir = Path(__file__).parent

config_file = exe_dir / 'config.ini'

if config_file.exists():
    config.read(config_file)
    TRACKER_HOST = config.get('Network', 'TRACKER_HOST', fallback='0.0.0.0')
    TRACKER_PORT = config.getint('Ports', 'TRACKER_PORT', fallback=5000)
else:
    TRACKER_HOST = '0.0.0.0'  # Listen on all network interfaces
    TRACKER_PORT = 5000

MAX_CLIENTS = 100

class Tracker:
    def __init__(self, host=TRACKER_HOST, port=TRACKER_PORT):
        self.host = host
        self.port = port
        self.server_socket = None
        self.peers = {}  # Format: {peer_id: {'host': str, 'port': int, 'files': {filename: size}}}
        self.lock = threading.Lock()
        self.running = False
        
    def start(self):
        """Start the tracker server"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(100)
            self.running = True
            
            print(f"[TRACKER] Server started on {self.host}:{self.port}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for peer connections...")
            
            # Start cleanup daemon thread
            cleanup_thread = threading.Thread(target=self.cleanup_stale_peers, daemon=True)
            cleanup_thread.start()
            
            while self.running:
                try:
                    client_socket, client_address = self.server_socket.accept()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] New connection from {client_address}")
                    
                    # Handle peer in separate thread
                    peer_thread = threading.Thread(
                        target=self.handle_peer,
                        args=(client_socket, client_address),
                        daemon=False  # Don't use daemon, let cleanup happen properly
                    )
                    peer_thread.start()
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"[ERROR] Accept connection failed: {e}")
                    
        except Exception as e:
            print(f"[ERROR] Tracker startup failed: {e}")
        finally:
            self.stop()
    
    def cleanup_stale_peers(self):
        """Remove peers that haven't sent heartbeat in 120 seconds"""
        while self.running:
            try:
                threading.Event().wait(30)  # Check every 30 seconds
                current_time = time.time()
                with self.lock:
                    stale_peers = []
                    for peer_id, info in self.peers.items():
                        last_seen = info.get('last_seen', current_time)
                        if current_time - last_seen > 120:
                            stale_peers.append(peer_id)
                    
                    for peer_id in stale_peers:
                        del self.peers[peer_id]
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Removed stale peer: {peer_id} (no heartbeat for 120s)")
                    
                    if stale_peers:
                        active_count = len(self.peers)
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Active peers: {active_count}")
            except Exception as e:
                print(f"[ERROR] Cleanup thread error: {e}")
    
    def handle_peer(self, client_socket, client_address):
        """Handle communication with a peer"""
        peer_id = None
        try:
            while True:
                data = client_socket.recv(4096).decode('utf-8')
                
                if not data:
                    break
                
                message = json.loads(data)
                command = message.get('command')
                
                if command == 'register':
                    peer_id = f"{client_address[0]}:{message['port']}"
                    with self.lock:
                        self.peers[peer_id] = {
                            'host': client_address[0],
                            'port': message['port'],
                            'files': {},
                            'last_seen': time.time()
                        }
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Peer registered: {peer_id}")
                    client_socket.send(json.dumps({'status': 'registered', 'peer_id': peer_id}).encode('utf-8'))
                
                elif command == 'update_files':
                    if peer_id:
                        with self.lock:
                            self.peers[peer_id]['files'] = message.get('files', {})
                            self.peers[peer_id]['last_seen'] = time.time()
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Files updated for {peer_id}: {list(message.get('files', {}).keys())}")
                        client_socket.send(json.dumps({'status': 'files_updated'}).encode('utf-8'))
                
                elif command == 'get_peers':
                    # Return list of all active peers with their files
                    with self.lock:
                        peers_info = {}
                        for pid, info in self.peers.items():
                            # Skip peers that haven't been seen in 2 minutes (possibly dead)
                            if time.time() - info.get('last_seen', 0) < 120:
                                peers_info[pid] = {
                                    'host': info['host'],
                                    'port': info['port'],
                                    'files': info['files']
                                }
                        # Log what we're sending
                        active_peers = len(peers_info)
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Peer list requested by {peer_id} - Returning {active_peers} active peers")
                        for p_id, p_data in peers_info.items():
                            file_count = len(p_data.get('files', {}))
                            print(f"     {p_id}: {file_count} file(s)")
                    client_socket.send(json.dumps({'status': 'peers', 'peers': peers_info}).encode('utf-8'))
                
                elif command == 'heartbeat':
                    # Keep-alive ping from peer
                    with self.lock:
                        if peer_id and peer_id in self.peers:
                            self.peers[peer_id]['last_seen'] = time.time()
                    client_socket.send(json.dumps({'status': 'pong'}).encode('utf-8'))
                    
                else:
                    client_socket.send(json.dumps({'status': 'error', 'message': 'unknown_command'}).encode('utf-8'))
                    
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON decode error from {client_address}: {e}")
        except Exception as e:
            print(f"[ERROR] Peer handler error for {client_address}: {e}")
        finally:
            if peer_id:
                with self.lock:
                    if peer_id in self.peers:
                        del self.peers[peer_id]
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Peer disconnected: {peer_id}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Peer disconnected: {peer_id}")
            client_socket.close()
    
    def stop(self):
        """Stop the tracker server"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print("[TRACKER] Server stopped")


if __name__ == '__main__':
    tracker = Tracker()
    try:
        tracker.start()
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down tracker...")
        tracker.stop()
