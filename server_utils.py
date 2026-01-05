import json
import struct
import base64
import os
import random
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import server_config as cfg
import server_state as state

def send_json(conn, data):
    try:
        msg = json.dumps(data).encode('utf-8')
        conn.sendall(struct.pack('>I', len(msg)) + msg)
    except: pass

def recvall(sock, n):
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet: return None
        data.extend(packet)
    return data

def recv_json(conn):
    try:
        raw_msglen = recvall(conn, 4)
        if not raw_msglen: return None
        msglen = struct.unpack('>I', raw_msglen)[0]
        data = recvall(conn, msglen)
        return json.loads(data.decode('utf-8'))
    except: return None

def save_file_to_disk(b64_data, file_ext="png"):
    try:
        file_data = base64.b64decode(b64_data)
        filename = f"{datetime.now().timestamp()}_{random.randint(1000,9999)}.{file_ext}"
        filepath = os.path.join(cfg.UPLOAD_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(file_data)
        return filename
    except Exception as e:
        print(f"Save error: {e}")
        return None

def load_file_b64(path):
    if not path or not os.path.exists(path): return None
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except: return None

def get_file_hash(path):
    """Вычисляет MD5 хеш файла"""
    if not path or not os.path.exists(path):
        return None
    try:
        hasher = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None

def send_email(to, code):
    if "your_email" in cfg.SMTP_EMAIL: return
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Код подтверждения NovCord"
    msg['From'] = cfg.SMTP_EMAIL
    msg['To'] = to
    
    # Красивый HTML шаблон
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #2b2d31; color: #ffffff; padding: 20px; }}
            .container {{ max-width: 500px; margin: 0 auto; background-color: #313338; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }}
            .header {{ background-color: #5865F2; padding: 20px; text-align: center; }}
            .header h1 {{ margin: 0; color: white; font-size: 24px; }}
            .content {{ padding: 30px; text-align: center; }}
            .code-box {{ background-color: #1e1f22; border-radius: 4px; padding: 15px; margin: 20px 0; font-size: 32px; letter-spacing: 5px; font-weight: bold; color: #eb459e; border: 1px dashed #5865F2; }}
            .footer {{ background-color: #1e1f22; padding: 15px; text-align: center; font-size: 12px; color: #949ba4; }}
            p {{ margin-bottom: 10px; line-height: 1.5; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>NovCord</h1>
            </div>
            <div class="content">
                <p>Привет! Спасибо за регистрацию.</p>
                <p>Ваш код подтверждения:</p>
                <div class="code-box">{code}</div>
                <p>Никому не сообщайте этот код.</p>
            </div>
            <div class="footer">
                &copy; {datetime.now().year} NovCord Team. All rights reserved.
            </div>
        </div>
    </body>
    </html>
    """
    
    msg.attach(MIMEText(html, 'html'))
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
            s.login(cfg.SMTP_EMAIL, cfg.SMTP_PASSWORD)
            s.send_message(msg)
    except Exception as e:
        print(f"Email send error: {e}")

def broadcast_to_user(user_id, message):
    with state.clients_lock:
        if user_id in state.connected_clients:
            try: send_json(state.connected_clients[user_id], message)
            except: pass

def broadcast_all(message):
    with state.clients_lock:
        for uid, conn in state.connected_clients.items():
            try: send_json(conn, message)
            except: pass