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
                return True
        except Exception as e:
            self.log(f"Failed to connect to tracker: {e}")
            messagebox.showerror("Connection Error", f"Cannot connect to tracker at {TRACKER_HOST}:{TRACKER_PORT}\n\nMake sure the tracker server is running!")
            return False
    
    def start_file_server(self):
        """Start a socket server to serve files to other peers"""
        def server_thread():
            try:
                self.file_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.file_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.file_server_socket.bind(('0.0.0.0', self.file_server_port))
                self.file_server_socket.listen(10)
                self.log(f"File server started on port {self.file_server_port}")
                
                while self.running:
                    try:
                        client_socket, client_address = self.file_server_socket.accept()
                        
                        # Handle file request in separate thread
                        handler = threading.Thread(
                            target=self.handle_file_request,
                            args=(client_socket, client_address),
                            daemon=True
                        )
                        handler.start()
                    except:
                        if self.running:
                            pass
                        else:
                            break
            except Exception as e:
                self.log(f"File server error: {e}")
        
        t = threading.Thread(target=server_thread, daemon=True)
        t.start()
    
    def handle_file_request(self, client_socket, client_address):
        """Handle incoming file requests from other peers"""
        try:
            # Receive file request
            request = json.loads(client_socket.recv(4096).decode('utf-8'))
            filename = request.get('filename')
            chunk_index = request.get('chunk_index', 0)
            
            if filename not in self.shared_files:
                response = {'status': 'error', 'message': 'file_not_found'}
                client_socket.send(json.dumps(response).encode('utf-8'))
                return
            
            file_path = self.shared_folder / filename
            
            if not file_path.exists():
                response = {'status': 'error', 'message': 'file_not_found'}
                client_socket.send(json.dumps(response).encode('utf-8'))
                return
            
            # Read and send file chunk
            with open(file_path, 'rb') as f:
                f.seek(chunk_index * CHUNK_SIZE)
                chunk_data = f.read(CHUNK_SIZE)
                
                response = {
                    'status': 'success',
                    'filename': filename,
                    'chunk_size': len(chunk_data),
                    'is_last': len(chunk_data) < CHUNK_SIZE
                }
                
                client_socket.send(json.dumps(response).encode('utf-8'))
                client_socket.sendall(chunk_data)
                
        except Exception as e:
            self.log(f"File request handler error: {e}")
        finally:
            client_socket.close()
    
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
            
            # Copy file to shared folder
            dest_path = self.shared_folder / file_path.name
            
            # Copy file (allow duplicate filenames - multiple seeders for same file)
            with open(file_path, 'rb') as src:
                with open(dest_path, 'wb') as dst:
                    dst.write(src.read())
            
            # Update shared files
            with self.lock:
                self.shared_files[file_path.name] = file_size
            
            self.log(f"File uploaded: {file_path.name} ({self.format_size(file_size)})")
            
            # Update tracker with new file list
            self.update_tracker_files()
            upload_path = self.shared_folder.resolve()
            messagebox.showinfo("Success", f"File '{file_path.name}' is now being shared!\n\nLocation: {upload_path / file_path.name}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to upload file: {e}")
            self.log(f"Upload failed: {e}")
    
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
            
            # Create empty file
            with open(file_dest, 'wb') as f:
                f.write(b'\x00' * file_size)
            
            def download_chunk(chunk_index, peer_id, peer_host, peer_port):
                """Download a specific chunk from a peer"""
                try:
                    peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    peer_socket.connect((peer_host, peer_port))
                    
                    request = {
                        'filename': filename,
                        'chunk_index': chunk_index
                    }
                    peer_socket.send(json.dumps(request).encode('utf-8'))
                    
                    response = json.loads(peer_socket.recv(4096).decode('utf-8'))
                    
                    if response.get('status') == 'success':
                        chunk_data = b''
                        chunk_size = response.get('chunk_size', 0)
                        
                        # Receive chunk data
                        while len(chunk_data) < chunk_size:
                            data = peer_socket.recv(min(16384, chunk_size - len(chunk_data)))
                            if not data:
                                break
                            chunk_data += data
                        
                        with chunks_lock:
                            chunks_data[chunk_index] = chunk_data
                        
                        progress_pct = int((len(chunks_data) / total_chunks) * 100)
                        self.update_progress(progress_pct)
                        self.log(f"Downloaded chunk {chunk_index + 1}/{total_chunks} from {peer_id}")
                    
                    peer_socket.close()
                    
                except Exception as e:
                    self.log(f"Chunk download error (chunk {chunk_index}): {e}")
            
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
            
            # Write chunks to file in order
            with open(file_dest, 'wb') as f:
                for chunk_idx in range(total_chunks):
                    if chunk_idx in chunks_data:
                        f.write(chunks_data[chunk_idx])
            
            self.log(f"Download complete: {filename}")
            self.update_progress(100)
            download_path = Path('downloads').resolve()
            messagebox.showinfo("Success", f"File '{filename}' downloaded successfully!\n\nLocation: {download_path / filename}")
            
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
