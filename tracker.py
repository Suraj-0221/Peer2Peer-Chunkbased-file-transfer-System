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
            self.server_socket.listen(MAX_CLIENTS)
            self.running = True
            
            print(f"[TRACKER] Server started on {self.host}:{self.port}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for peer connections...")
            
            while self.running:
                try:
                    client_socket, client_address = self.server_socket.accept()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] New connection from {client_address}")
                    
                    # Handle peer in separate thread
                    peer_thread = threading.Thread(
                        target=self.handle_peer,
                        args=(client_socket, client_address),
                        daemon=True
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
                            'files': {}
                        }
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Peer registered: {peer_id}")
                    client_socket.send(json.dumps({'status': 'registered', 'peer_id': peer_id}).encode('utf-8'))
                
                elif command == 'update_files':
                    if peer_id:
                        with self.lock:
                            self.peers[peer_id]['files'] = message.get('files', {})
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Files updated for {peer_id}: {list(message.get('files', {}).keys())}")
                        client_socket.send(json.dumps({'status': 'files_updated'}).encode('utf-8'))
                
                elif command == 'get_peers':
                    # Return list of all peers with their files
                    with self.lock:
                        peers_info = {}
                        for pid, info in self.peers.items():
                            peers_info[pid] = {
                                'host': info['host'],
                                'port': info['port'],
                                'files': info['files']
                            }
                        # Log what we're sending
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Returning peers: {len(peers_info)} peers")
                        for peer_id, peer_data in peers_info.items():
                            print(f"     {peer_id}: {list(peer_data.get('files', {}).keys())}")
                    client_socket.send(json.dumps({'status': 'peers', 'peers': peers_info}).encode('utf-8'))
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Peer list requested by {peer_id}")
                
                elif command == 'heartbeat':
                    # Keep-alive ping from peer
                    with self.lock:
                        if peer_id in self.peers:
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
