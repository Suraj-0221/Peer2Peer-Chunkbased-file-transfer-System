#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2P File Sharing - Peer Client with GUI
Peer node that can upload and download files
"""

import tkinter as tk
from tkinter import (filedialog, messagebox, ttk, scrolledtext)
import socket
import threading
import json
import os
from pathlib import Path
from datetime import datetime
import io
import configparser
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
    TRACKER_HOST = config.get('Network', 'TRACKER_HOST', fallback='localhost')
    TRACKER_PORT = config.getint('Ports', 'TRACKER_PORT', fallback=5000)
    STARTING_PORT = config.getint('Ports', 'STARTING_PEER_PORT', fallback=5001)
    DOWNLOAD_DIR = config.get('Download', 'DOWNLOAD_DIR', fallback='./downloads/')
    CHUNK_SIZE = config.getint('Performance', 'CHUNK_SIZE', fallback=65536)
    MAX_CONCURRENT_DOWNLOADS = config.getint('Performance', 'MAX_CONCURRENT_DOWNLOADS', fallback=3)
else:
    TRACKER_HOST = 'localhost'
    TRACKER_PORT = 5000
    STARTING_PORT = 5001
    DOWNLOAD_DIR = './downloads/'
    CHUNK_SIZE = 65536
    MAX_CONCURRENT_DOWNLOADS = 3

class PeerClient:
    def __init__(self):
        self.peer_id = None
        self.tracker_socket = None
        self.file_server_socket = None
        self.shared_files = {}  # {filename: size}
        
        # Find available port for this peer
        self.file_server_port = self.find_available_port(STARTING_PORT)
        self.shared_folder = Path('shared_files')
        self.shared_folder.mkdir(exist_ok=True)
        
        self.available_files = {}  # {peer_id: {filename: size}}
        self.download_threads = []
        self.lock = threading.Lock()
        self.running = False
        
        # GUI references
        self.root = None
        self.log_widget = None
        self.files_listbox = None
        self.download_progress = None
        self.status_label = None
        
        # Scan existing files in shared folder on startup
        self.rescan_shared_folder()
    
    @staticmethod
    def find_available_port(start_port=5001):
        """Find an available port starting from start_port"""
        port = start_port
        max_attempts = 50
        for attempt in range(max_attempts):
            try:
                test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_socket.bind(('0.0.0.0', port))
                test_socket.close()
                return port
            except OSError:
                port += 1
        raise Exception(f"Could not find available port starting from {start_port}")
    
    def rescan_shared_folder(self):
        """Scan shared_files folder and populate shared_files dict"""
        try:
            if self.shared_folder.exists():
                with self.lock:
                    self.shared_files.clear()
                    for file_path in self.shared_folder.iterdir():
                        if file_path.is_file():
                            file_size = file_path.stat().st_size
                            self.shared_files[file_path.name] = file_size
                
                if self.shared_files:
                    self.log(f"Found {len(self.shared_files)} existing file(s) in shared folder")
                    for filename, size in self.shared_files.items():
                        self.log(f"  - {filename} ({self.format_size(size)})")
        except Exception as e:
            self.log(f"Error scanning shared folder: {e}")
    
    def rescan_and_update(self):
        """Rescan shared folder and update tracker with new file list"""
        self.rescan_shared_folder()
        self.update_tracker_files()
        self.log(f"Shared folder rescanned - reporting {len(self.shared_files)} file(s) to tracker")
        messagebox.showinfo("Rescan Complete", f"Found {len(self.shared_files)} file(s) in shared folder")
        
    def log(self, message):
        """Add message to log with timestamp"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] {message}"
        print(full_msg)
        
        if self.log_widget:
            self.log_widget.config(state=tk.NORMAL)
            self.log_widget.insert(tk.END, full_msg + '\n')
            self.log_widget.see(tk.END)
            self.log_widget.config(state=tk.DISABLED)
    
    def connect_to_tracker(self):
        """Connect this peer to the tracker server"""
        try:
            self.tracker_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tracker_socket.connect((TRACKER_HOST, TRACKER_PORT))
            
            # Register with tracker
            register_msg = {
                'command': 'register',
                'port': self.file_server_port
            }
            self.tracker_socket.send(json.dumps(register_msg).encode('utf-8'))
            
            # Wait for registration confirmation
            response = json.loads(self.tracker_socket.recv(4096).decode('utf-8'))
            if response.get('status') == 'registered':
                self.peer_id = response.get('peer_id')
                self.log(f"Connected to tracker. Peer ID: {self.peer_id}")
                self.running = True
                self.start_file_server()
                self.start_heartbeat()
                
                # Send all shared files to tracker immediately after registration
                import time
                time.sleep(0.5)  # Brief delay to ensure connection is ready
                self.update_tracker_files()
                
                return True
        except Exception as e:
            self.log(f"Failed to connect to tracker: {e}")
            messagebox.showerror("Connection Error", f"Cannot connect to tracker at {TRACKER_HOST}:{TRACKER_PORT}\n\nMake sure the tracker server is running!")
            return False
    
    def start_file_server(self):
        """Start a socket server to serve files to other peers"""
        def server_thread():
            active_connections = 0
            max_active = 20  # Limit concurrent connections
            try:
                self.file_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.file_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.file_server_socket.bind(('0.0.0.0', self.file_server_port))
                self.file_server_socket.listen(20)  # Increased listen backlog
                self.log(f"File server started on port {self.file_server_port}")
                
                while self.running:
                    try:
                        client_socket, client_address = self.file_server_socket.accept()
                        
                        # Limit concurrent connections to prevent resource exhaustion
                        active_connections += 1
                        if active_connections > max_active:
                            self.log(f"⚠ Connection limit reached ({active_connections}), rejecting new connection")
                            client_socket.close()
                            active_connections -= 1
                            continue
                        
                        # Handle file request in separate thread
                        def handle_with_cleanup(sock, addr, conn_count):
                            try:
                                self.handle_file_request(sock, addr)
                            finally:
                                nonlocal active_connections
                                active_connections -= 1
                        
                        handler = threading.Thread(
                            target=handle_with_cleanup,
                            args=(client_socket, client_address, active_connections),
                            daemon=False  # Changed to False to ensure cleanup
                        )
                        handler.start()
                    except Exception as e:
                        if self.running:
                            self.log(f"Error accepting connection: {e}")
                        else:
                            break
            except Exception as e:
                self.log(f"File server error: {e}")
            finally:
                try:
                    if self.file_server_socket:
                        self.file_server_socket.close()
                except:
                    pass
        
        t = threading.Thread(target=server_thread, daemon=True)
        t.start()
    
    def handle_file_request(self, client_socket, client_address):
        """Handle incoming file requests from other peers"""
        try:
            # Set socket timeouts and buffers for reliable transfer
            client_socket.settimeout(120)  # 2 minute timeout for slow networks
            client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256KB
            client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)  # 256KB
            
            # Receive file request with length prefix
            request_len_bytes = client_socket.recv(4)
            if not request_len_bytes or len(request_len_bytes) < 4:
                return
            
            request_len = int.from_bytes(request_len_bytes, 'big')
            if request_len > 10000:  # Sanity check
                self.log(f"Invalid request length from {client_address}: {request_len}")
                return
                
            request_data = b''
            while len(request_data) < request_len:
                chunk = client_socket.recv(request_len - len(request_data))
                if not chunk:
                    break
                request_data += chunk
            
            request = json.loads(request_data.decode('utf-8'))
            filename = request.get('filename')
            chunk_index = request.get('chunk_index', 0)
            
            if not filename or filename not in self.shared_files:
                response = {'status': 'error', 'message': 'file_not_found'}
                response_json = json.dumps(response).encode('utf-8')
                try:
                    client_socket.sendall(len(response_json).to_bytes(4, 'big'))
                    client_socket.sendall(response_json)
                except:
                    pass
                return
            
            file_path = self.shared_folder / filename
            
            if not file_path.exists():
                response = {'status': 'error', 'message': 'file_not_found'}
                response_json = json.dumps(response).encode('utf-8')
                try:
                    client_socket.sendall(len(response_json).to_bytes(4, 'big'))
                    client_socket.sendall(response_json)
                except:
                    pass
                return
            
            # Read and send file chunk
            try:
                with open(file_path, 'rb') as f:
                    f.seek(chunk_index * CHUNK_SIZE)
                    chunk_data = f.read(CHUNK_SIZE)
                    
                    response = {
                        'status': 'success',
                        'filename': filename,
                        'chunk_index': chunk_index,
                        'chunk_size': len(chunk_data),
                        'is_last': len(chunk_data) < CHUNK_SIZE
                    }
                    
                    # Send response with length prefix
                    response_json = json.dumps(response).encode('utf-8')
                    response_len = len(response_json)
                    
                    # Send: [4 bytes length][JSON header][binary chunk]
                    client_socket.sendall(response_len.to_bytes(4, 'big'))
                    client_socket.sendall(response_json)
                    
                    # Send binary data in smaller chunks to avoid socket buffer issues
                    bytes_sent = 0
                    while bytes_sent < len(chunk_data):
                        to_send = min(32768, len(chunk_data) - bytes_sent)
                        client_socket.sendall(chunk_data[bytes_sent:bytes_sent + to_send])
                        bytes_sent += to_send
                    
                    self.log(f"Sent chunk {chunk_index + 1} of '{filename}' to {client_address[0]}")
            except socket.timeout:
                self.log(f"Socket timeout sending chunk {chunk_index} to {client_address}")
            except Exception as send_err:
                self.log(f"Error sending chunk {chunk_index}: {send_err}")
                
        except socket.timeout:
            self.log(f"Timeout in file request handler from {client_address}")
        except Exception as e:
            self.log(f"File request handler error: {e}")
        finally:
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                client_socket.close()
            except:
                pass
    
    def start_heartbeat(self):
        """Send periodic heartbeat to tracker"""
        def heartbeat():
            while self.running:
                try:
                    threading.Event().wait(30)  # Wait 30 seconds
                    if self.tracker_socket:
                        msg = {'command': 'heartbeat'}
                        self.tracker_socket.send(json.dumps(msg).encode('utf-8'))
                        self.tracker_socket.recv(1024)
                except:
                    pass
        
        t = threading.Thread(target=heartbeat, daemon=True)
        t.start()
    
    def upload_file(self):
        """Allow user to select and upload a file"""
        file_path = filedialog.askopenfilename(
            title="Select file to share",
            initialdir=str(Path.home() / "Documents")
        )
        
        if not file_path:
            return
        
        try:
            file_path = Path(file_path)
            file_size = file_path.stat().st_size
            
            # Copy file to shared folder with verified integrity
            dest_path = self.shared_folder / file_path.name
            
            # Copy file in chunks to handle large files
            with open(file_path, 'rb') as src:
                with open(dest_path, 'wb') as dst:
                    bytes_copied = 0
                    while True:
                        chunk = src.read(1024 * 1024)  # 1MB chunks
                        if not chunk:
                            break
                        dst.write(chunk)
                        bytes_copied += len(chunk)
            
            # Verify file was copied correctly
            dest_size = dest_path.stat().st_size
            if dest_size != file_size:
                raise Exception(f"File copy failed: source {file_size} bytes, copied {dest_size} bytes")
            
            # Update shared files
            with self.lock:
                self.shared_files[file_path.name] = file_size
            
            self.log(f"File uploaded: {file_path.name} ({self.format_size(file_size)}) - Verified OK")
            
            # Update tracker with new file list
            self.update_tracker_files()
            upload_path = self.shared_folder.resolve()
            messagebox.showinfo("Success", f"File '{file_path.name}' is now being shared!\n\nLocation: {upload_path / file_path.name}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to upload file: {e}")
            self.log(f"Upload failed: {e}")
    
    def add_file_to_sharing(self, source_path):
        """Add a file to the shared_files folder and update tracker"""
        try:
            source_path = Path(source_path)
            if not source_path.exists():
                self.log(f"File not found: {source_path}")
                return False
            
            dest_path = self.shared_folder / source_path.name
            
            # If file is already in shared folder, no need to copy
            if source_path.resolve() == dest_path.resolve():
                with self.lock:
                    if source_path.name not in self.shared_files:
                        self.shared_files[source_path.name] = source_path.stat().st_size
            else:
                # Copy file to shared folder
                file_size = source_path.stat().st_size
                with open(source_path, 'rb') as src:
                    with open(dest_path, 'wb') as dst:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            dst.write(chunk)
                
                # Verify copy
                if dest_path.stat().st_size != file_size:
                    raise Exception(f"Copy verification failed")
                
                with self.lock:
                    self.shared_files[source_path.name] = file_size
                
                self.log(f"Copied '{source_path.name}' to shared folder")
            
            # Update tracker
            self.update_tracker_files()
            self.log(f"✓ Now seeding '{source_path.name}'")
            return True
            
        except Exception as e:
            self.log(f"Failed to add file to sharing: {e}")
            messagebox.showerror("Error", f"Could not add file to sharing: {e}")
            return False
    
    def update_tracker_files(self):
        """Update tracker with current shared files"""
        try:
            if self.tracker_socket:
                msg = {
                    'command': 'update_files',
                    'files': self.shared_files.copy()
                }
                self.tracker_socket.send(json.dumps(msg).encode('utf-8'))
                self.tracker_socket.recv(1024)
        except Exception as e:
            self.log(f"Failed to update tracker: {e}")
    
    def refresh_files(self):
        """Get list of available files from tracker"""
        try:
            if self.tracker_socket:
                msg = {'command': 'get_peers'}
                self.tracker_socket.send(json.dumps(msg).encode('utf-8'))
                response = json.loads(self.tracker_socket.recv(65536).decode('utf-8'))
                
                with self.lock:
                    self.available_files.clear()
                    peers = response.get('peers', {})
                    
                    for peer_id, peer_info in peers.items():
                        files = peer_info.get('files', {})
                        if files:
                            self.available_files[peer_id] = files
                
                self.update_files_display()
                
                # Log consolidated file info (by filename with seeder count)
                file_seeders = {}
                for peer_id, files in self.available_files.items():
                    for filename in files.keys():
                        if filename not in file_seeders:
                            file_seeders[filename] = 0
                        file_seeders[filename] += 1
                
                for filename, seeder_count in sorted(file_seeders.items()):
                    seeder_text = "seeder" if seeder_count == 1 else "seeders"
                    self.log(f"Found '{filename}' - {seeder_count} {seeder_text}")
                
                if file_seeders:
                    peer_count = len(self.available_files)
                    peer_text = "peer" if peer_count == 1 else "peers"
                    self.log(f"Refreshed file list. Found {len(file_seeders)} unique file(s) from {peer_count} {peer_text}")
                else:
                    self.log("Refreshed file list. No files available")
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh files: {e}")
            self.log(f"Refresh failed: {e}")
    
    def update_files_display(self):
        """Update the GUI file list - consolidate same files into one entry with seeder count"""
        if self.files_listbox:
            self.files_listbox.config(state=tk.NORMAL)
            self.files_listbox.delete(0, tk.END)
            
            # Group files by filename and track seeders
            file_seeders = {}  # {filename: {'size': X, 'peers': [peer_id1, peer_id2, ...]}}
            
            for peer_id, files in self.available_files.items():
                for filename, size in files.items():
                    if filename not in file_seeders:
                        file_seeders[filename] = {'size': size, 'peers': []}
                    file_seeders[filename]['peers'].append(peer_id)
            
            # Display each unique file with seeder count
            for filename in sorted(file_seeders.keys()):
                info = file_seeders[filename]
                seeder_count = len(info['peers'])
                size_str = self.format_size(info['size'])
                
                if seeder_count == 1:
                    display_text = f"{filename} ({size_str}) - 1 seeder"
                else:
                    display_text = f"{filename} ({size_str}) - {seeder_count} seeders"
                
                self.files_listbox.insert(tk.END, display_text)
            
            # Keep listbox enabled for selection
            self.files_listbox.config(state=tk.NORMAL)
    
    def download_file(self):
        """Download selected file from peers"""
        if not self.files_listbox:
            return
        
        selection = self.files_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a file to download")
            return
        
        selected_text = self.files_listbox.get(selection[0])
        
        # Parse selected file - format is "filename (size) - N seeder(s)"
        try:
            # Extract filename by removing the "(size) - N seeder(s)" part
            parts = selected_text.rsplit(' - ', 1)  # Split off the "N seeder(s)"
            file_info = parts[0].rsplit(' (', 1)     # Split off the size
            filename = file_info[0]
            
            # Find peers that have this file
            peers_with_file = []
            for peer_id, files in self.available_files.items():
                if filename in files:
                    peers_with_file.append((peer_id, files[filename]))
            
            if not peers_with_file:
                messagebox.showerror("Error", "File not found on any peer")
                return
            
            # Ask for confirmation
            seeders_count = len(peers_with_file)
            size_info = f"{self.format_size(peers_with_file[0][1])}"
            result = messagebox.askyesno(
                "Confirm Download",
                f"Download '{filename}' ({size_info})?\nAvailable seeders: {seeders_count}"
            )
            
            if result:
                download_thread = threading.Thread(
                    target=self.perform_download,
                    args=(filename, peers_with_file),
                    daemon=True
                )
                download_thread.start()
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse selection: {e}")
    
    def perform_download(self, filename, peers_with_file):
        """Download file from peers with chunk-based parallel downloading"""
        try:
            file_size = peers_with_file[0][1]
            total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
            
            self.log(f"Starting download: {filename} ({self.format_size(file_size)}) - {len(peers_with_file)} seeders")
            
            download_path = Path('downloads')
            download_path.mkdir(exist_ok=True)
            
            file_dest = download_path / filename
            chunks_data = {}
            chunks_lock = threading.Lock()
            failed_chunks = set()
            
            # Create empty file with proper size (filled with zeros)
            with open(file_dest, 'wb') as f:
                f.write(b'\x00' * file_size)
            
            def download_chunk(chunk_index, peer_id, peer_host, peer_port, retry_count=0):
                """Download a specific chunk from a peer with robust retry logic"""
                max_retries = 5  # Increased from 3 to 5
                peer_socket = None
                try:
                    # Exponential backoff: wait longer between retries
                    if retry_count > 0:
                        wait_time = min(2 ** retry_count, 30)  # Max 30 seconds wait
                        self.log(f"Waiting {wait_time}s before retrying chunk {chunk_index + 1}/{total_chunks}...")
                        import time
                        time.sleep(wait_time)
                    
                    peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    # Increase timeout and set buffer sizes
                    peer_socket.settimeout(60)  # 60 second timeout (was 30)
                    peer_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256KB buffer
                    peer_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)  # 256KB buffer
                    
                    peer_socket.connect((peer_host, peer_port))
                    
                    request = {
                        'filename': filename,
                        'chunk_index': chunk_index
                    }
                    request_json = json.dumps(request).encode('utf-8')
                    
                    # Send request with length prefix: [4 bytes length][JSON]
                    request_len = len(request_json)
                    peer_socket.sendall(request_len.to_bytes(4, 'big'))
                    peer_socket.sendall(request_json)
                    
                    # Receive response header length (first 4 bytes)
                    response_len_bytes = b''
                    while len(response_len_bytes) < 4:
                        chunk = peer_socket.recv(4 - len(response_len_bytes))
                        if not chunk:
                            raise Exception("Connection closed: peer didn't send response length")
                        response_len_bytes += chunk
                    
                    response_len = int.from_bytes(response_len_bytes, 'big')
                    if response_len > 10000:  # Sanity check - JSON should be < 1KB
                        raise Exception(f"Invalid response length: {response_len} bytes (corrupted header)")
                    
                    # Receive exact amount of JSON response data
                    response_data = b''
                    while len(response_data) < response_len:
                        try:
                            chunk = peer_socket.recv(response_len - len(response_data))
                        except socket.timeout:
                            raise Exception(f"Timeout receiving response header at {len(response_data)}/{response_len} bytes")
                        if not chunk:
                            raise Exception(f"Connection closed during response: got {len(response_data)}/{response_len} bytes")
                        response_data += chunk
                    
                    response = json.loads(response_data.decode('utf-8'))
                    
                    if response.get('status') == 'success':
                        chunk_size = response.get('chunk_size', 0)
                        if chunk_size == 0:
                            # Empty chunk might be end of file
                            self.log(f"Downloaded empty chunk {chunk_index + 1}/{total_chunks} (EOF)")
                            with chunks_lock:
                                chunks_data[chunk_index] = b''
                                if chunk_index in failed_chunks:
                                    failed_chunks.discard(chunk_index)
                        else:
                            # Receive binary chunk data (exactly chunk_size bytes)
                            chunk_data = b''
                            timeout_count = 0
                            while len(chunk_data) < chunk_size:
                                try:
                                    data = peer_socket.recv(min(32768, chunk_size - len(chunk_data)))
                                except socket.timeout:
                                    timeout_count += 1
                                    if timeout_count > 3:
                                        raise Exception(f"Multiple timeouts receiving chunk data. Got {len(chunk_data)}/{chunk_size} bytes")
                                    self.log(f"Timeout on chunk {chunk_index + 1} (got {len(chunk_data)}/{chunk_size}), retrying...")
                                    continue
                                
                                if not data:
                                    raise Exception(f"Connection lost while downloading chunk {chunk_index}. Got {len(chunk_data)}/{chunk_size} bytes")
                                chunk_data += data
                            
                            if len(chunk_data) != chunk_size:
                                raise Exception(f"Chunk size mismatch: expected {chunk_size}, got {len(chunk_data)}")
                            
                            with chunks_lock:
                                chunks_data[chunk_index] = chunk_data
                                if chunk_index in failed_chunks:
                                    failed_chunks.discard(chunk_index)
                        
                        progress_pct = int((len(chunks_data) / total_chunks) * 100)
                        self.update_progress(progress_pct)
                        self.log(f"✓ Downloaded chunk {chunk_index + 1}/{total_chunks} from {peer_id}")
                    else:
                        error_msg = response.get('message', 'Unknown error')
                        raise Exception(f"Peer error: {error_msg}")
                    
                    peer_socket.close()
                    
                except Exception as e:
                    if peer_socket:
                        try:
                            peer_socket.close()
                        except:
                            pass
                    
                    with chunks_lock:
                        failed_chunks.add(chunk_index)
                    
                    if retry_count < max_retries:
                        self.log(f"⚠ Chunk {chunk_index + 1}/{total_chunks} failed (attempt {retry_count + 1}/{max_retries + 1}): {str(e)[:80]}")
                        # Try next available peer
                        try:
                            peer_idx = (peers_with_file.index((peer_id, file_size)) + 1) % len(peers_with_file)
                            next_peer_id, _ = peers_with_file[peer_idx]
                            host_port = next_peer_id.split(':')
                            next_host = host_port[0]
                            next_port = int(host_port[1]) if len(host_port) > 1 else self.file_server_port
                            threading.Thread(
                                target=download_chunk,
                                args=(chunk_index, next_peer_id, next_host, next_port, retry_count + 1),
                                daemon=True
                            ).start()
                        except Exception as retry_err:
                            self.log(f"Could not retry chunk {chunk_index + 1}: {retry_err}")
                    else:
                        self.log(f"✗ FAILED chunk {chunk_index + 1}/{total_chunks} after {max_retries + 1} attempts")
            
            # Get peer host and port info
            peers_info = {}
            for peer_id, _ in peers_with_file:
                host_port = peer_id.split(':')
                peers_info[peer_id] = {
                    'host': host_port[0],
                    'port': int(host_port[1]) if len(host_port) > 1 else self.file_server_port
                }
            
            # Download chunks from multiple peers
            active_threads = []
            peer_list = list(peers_info.items())
            
            for chunk_idx in range(total_chunks):
                # Select peer in round-robin fashion
                peer_id, peer_info = peer_list[chunk_idx % len(peer_list)]
                
                t = threading.Thread(
                    target=download_chunk,
                    args=(chunk_idx, peer_id, peer_info['host'], peer_info['port']),
                    daemon=True
                )
                t.start()
                active_threads.append(t)
                
                # Limit concurrent downloads
                if len(active_threads) >= MAX_CONCURRENT_DOWNLOADS:
                    for thread in active_threads:
                        thread.join()
                    active_threads = []
            
            # Wait for all downloads to complete
            for thread in active_threads:
                thread.join()
            
            # Final wait for any remaining retry threads
            import time
            max_wait = 60  # Wait up to 60 seconds for retries
            wait_time = 0
            while len(chunks_data) < total_chunks and wait_time < max_wait:
                time.sleep(0.5)
                wait_time += 0.5
            
            # Write chunks to file at correct offsets
            with open(file_dest, 'r+b') as f:
                for chunk_idx in range(total_chunks):
                    if chunk_idx in chunks_data:
                        f.seek(chunk_idx * CHUNK_SIZE)
                        f.write(chunks_data[chunk_idx])
                    elif chunk_idx not in failed_chunks:
                        self.log(f"Warning: Chunk {chunk_idx + 1}/{total_chunks} not downloaded")
                    else:
                        self.log(f"Error: Chunk {chunk_idx + 1}/{total_chunks} failed to download")
            
            # Verify file completeness
            final_size = file_dest.stat().st_size
            if final_size != file_size:
                self.log(f"WARNING: Downloaded file size ({self.format_size(final_size)}) does not match expected size ({self.format_size(file_size)})")
            
            if failed_chunks:
                self.log(f"Download incomplete: {len(failed_chunks)} chunk(s) failed to download")
                messagebox.showwarning("Download Incomplete", f"File downloaded but {len(failed_chunks)} chunk(s) failed.\n\nFile: {file_dest}\nSize: {self.format_size(final_size)}")
            else:
                self.log(f"Download complete: {filename} ({self.format_size(final_size)})")
                self.update_progress(100)
                
                # Ask if user wants to share this file
                result = messagebox.askyesno(
                    "Download Complete",
                    f"File '{filename}' downloaded successfully!\n\nLocation: {file_dest.resolve()}\n\nDo you want to share this file with other peers?"
                )
                
                if result:
                    # Auto-add to sharing
                    self.add_file_to_sharing(file_dest.resolve())
                    self.log(f"★ File '{filename}' is now being shared as a seeder!")
            
        except Exception as e:
            messagebox.showerror("Download Error", f"Failed to download file: {e}")
            self.log(f"Download error: {e}")
    
    def update_progress(self, percentage):
        """Update progress bar"""
        if self.download_progress:
            self.download_progress['value'] = percentage
            self.root.update_idletasks()
    
    @staticmethod
    def format_size(size_bytes):
        """Format bytes to human-readable size"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"
    
    def create_gui(self):
        """Create the GUI window"""
        self.root = tk.Tk()
        self.root.title("P2P File Sharing - Peer Client")
        self.root.geometry("900x700")
        self.root.config(bg='white')
        
        # Style configuration
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', font=('Segoe UI', 11))
        style.configure('TLabel', font=('Segoe UI', 11), background='white')
        style.configure('TLabelframe', font=('Segoe UI', 11, 'bold'), background='white')
        
        # Main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        title_label = ttk.Label(header_frame, text="P2P File Sharing Network", font=('Segoe UI', 16, 'bold'))
        title_label.pack(side=tk.LEFT)
        
        self.status_label = ttk.Label(header_frame, text="Connecting...", font=('Segoe UI', 10))
        self.status_label.pack(side=tk.RIGHT)
        
        # Separator
        ttk.Separator(main_frame, orient='horizontal').pack(fill=tk.X, pady=10)
        
        # Control buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        upload_btn = ttk.Button(button_frame, text="📤 Upload File", command=self.upload_file)
        upload_btn.pack(side=tk.LEFT, padx=5)
        
        rescan_btn = ttk.Button(button_frame, text="🔍 Rescan Folder", command=self.rescan_and_update)
        rescan_btn.pack(side=tk.LEFT, padx=5)
        
        refresh_btn = ttk.Button(button_frame, text="🔄 Refresh Files", command=self.refresh_files)
        refresh_btn.pack(side=tk.LEFT, padx=5)
        
        # Available files section
        files_frame = ttk.LabelFrame(main_frame, text="Available Files", padding=10)
        files_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # Files listbox
        scrollbar = ttk.Scrollbar(files_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.files_listbox = tk.Listbox(
            files_frame,
            yscrollcommand=scrollbar.set,
            font=('Segoe UI', 10),
            bg='#f5f5f5',
            height=12
        )
        self.files_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.files_listbox.yview)
        
        # Download button
        download_btn = ttk.Button(main_frame, text="⬇️ Download Selected File", command=self.download_file)
        download_btn.pack(fill=tk.X, pady=5)
        
        # Progress bar
        progress_label = ttk.Label(main_frame, text="Download Progress:")
        progress_label.pack(anchor=tk.W, pady=(10, 2))
        
        self.download_progress = ttk.Progressbar(
            main_frame,
            mode='determinate',
            value=0,
            length=400
        )
        self.download_progress.pack(fill=tk.X, pady=(0, 10))
        
        # Download info section
        download_info_frame = ttk.Frame(main_frame)
        download_info_frame.pack(fill=tk.X, pady=(0, 10))
        
        download_location_label = ttk.Label(
            download_info_frame, 
            text="📁 Downloads folder: ./downloads/",
            font=('Segoe UI', 9)
        )
        download_location_label.pack(side=tk.LEFT)
        
        def open_downloads():
            downloads_path = Path('downloads').resolve()
            downloads_path.mkdir(exist_ok=True)
            os.startfile(str(downloads_path))
        
        open_folder_btn = ttk.Button(download_info_frame, text="Open Folder", command=open_downloads)
        open_folder_btn.pack(side=tk.RIGHT, padx=5)
        
        # Log section
        log_frame = ttk.LabelFrame(main_frame, text="Activity Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        self.log_widget = scrolledtext.ScrolledText(
            log_frame,
            height=8,
            font=('Courier New', 9),
            bg='#f8f8f8',
            state=tk.DISABLED
        )
        self.log_widget.pack(fill=tk.BOTH, expand=True)
        
        # Footer
        footer_frame = ttk.Frame(main_frame)
        footer_frame.pack(fill=tk.X, pady=(10, 0))
        
        footer_label = ttk.Label(
            footer_frame,
            text="Shared folder: ./shared_files | Downloads: ./downloads",
            font=('Segoe UI', 9)
        )
        footer_label.pack(anchor=tk.W)
        
        # Connect to tracker
        def connect():
            if self.connect_to_tracker():
                self.status_label.config(text=f"✓ Connected - {self.peer_id}", foreground='green')
                self.refresh_files()
        
        connect_thread = threading.Thread(target=connect, daemon=True)
        connect_thread.start()
        
        # Handle window close
        def on_closing():
            self.running = False
            if self.file_server_socket:
                self.file_server_socket.close()
            if self.tracker_socket:
                self.tracker_socket.close()
            self.root.destroy()
        
        self.root.protocol("WM_DELETE_WINDOW", on_closing)
        self.root.mainloop()


if __name__ == '__main__':
    client = PeerClient()
    client.create_gui()
