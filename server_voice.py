import socket
import threading
import struct
import server_config as cfg
from server_logger import logger

class VoiceServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((cfg.HOST, cfg.VOICE_PORT))
        self.running = False
        
        # Mappings
        self.addr_to_user = {}  # (ip, port) -> user_id
        self.user_to_addr = {}  # user_id -> (ip, port)
        self.user_channels = {} # user_id -> channel_id (group_id or 'private_id')
        
        # Locks
        self.lock = threading.Lock()

    def start(self):
        self.running = True
        logger.info(f"Voice Server started on UDP port {cfg.VOICE_PORT}")
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096) # Standard MTU safe size
                
                # Protocol:
                # 1. Handshake: "VOICE_INIT:{user_id}"
                # 2. Audio Data: Raw Bytes
                
                if data.startswith(b"VOICE_INIT:"):
                    try:
                        user_id = int(data.decode().split(":")[1])
                        with self.lock:
                            self.addr_to_user[addr] = user_id
                            self.user_to_addr[user_id] = addr
                        # logger.info(f"Voice registered user {user_id} at {addr}")
                    except: pass
                    continue
                
                # Handling Audio Data
                with self.lock:
                    sender_id = self.addr_to_user.get(addr)
                    if not sender_id: continue
                    
                    channel_id = self.user_channels.get(sender_id)
                    if not channel_id: continue
                    
                    # Broadcast to others in same channel
                    # Packet format to client: [Sender ID (4 bytes)][Audio Data]
                    packet = struct.pack('>I', sender_id) + data
                    
                    for uid, cid in self.user_channels.items():
                        if cid == channel_id and uid != sender_id:
                            target_addr = self.user_to_addr.get(uid)
                            if target_addr:
                                self.sock.sendto(packet, target_addr)
                                
            except Exception as e:
                logger.error(f"Voice server error: {e}")

    def join_channel(self, user_id, channel_id):
        with self.lock:
            self.user_channels[user_id] = channel_id
            logger.info(f"User {user_id} joined voice channel {channel_id}")

    def leave_channel(self, user_id):
        with self.lock:
            if user_id in self.user_channels:
                del self.user_channels[user_id]
                logger.info(f"User {user_id} left voice channel")

# Global instance
voice_server = VoiceServer()