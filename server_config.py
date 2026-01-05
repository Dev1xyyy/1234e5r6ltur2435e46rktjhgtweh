import os
import sys
import shutil

# --- PATH LOGIC ---

def get_base_dir():
    """Возвращает директорию, где лежит exe или скрипт"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()

def unpack_if_missing(folder_name):
    """
    Распаковывает папку из ресурсов exe, если её нет рядом с exe.
    Нужно для первого запуска, чтобы достать дефолтные ассеты.
    """
    target_path = os.path.join(BASE_DIR, folder_name)
    
    # Если папка уже есть рядом с exe - ничего не делаем (чтобы не затереть данные)
    if os.path.exists(target_path):
        return target_path

    # Если запущено как exe, ищем ресурсы во временной папке _MEIPASS
    if getattr(sys, 'frozen', False):
        try:
            source_path = os.path.join(sys._MEIPASS, folder_name)
            if os.path.exists(source_path):
                print(f"First run: Unpacking '{folder_name}' to {target_path}...")
                shutil.copytree(source_path, target_path)
        except Exception as e:
            print(f"Error unpacking {folder_name}: {e}")
    
    # Если папки все еще нет (или не exe), создаем пустую
    if not os.path.exists(target_path):
        try:
            os.makedirs(target_path)
        except: pass
        
    return target_path

# --- NETWORK CONFIG ---
HOST = '0.0.0.0'
PORT = 65432
VOICE_PORT = 65433

# --- PATHS (Writeable) ---
# Инициализируем папки. Если их нет -> распакуются из exe.
# Если есть -> будут использоваться существующие.

DB_NAME = os.path.join(BASE_DIR, "novcord_server.db")
LOG_DIR = unpack_if_missing("logs")

# Эти папки важны для контента
UPLOAD_DIR = unpack_if_missing("server_files")
STICKERS_DIR = unpack_if_missing("stickers")
NFTS_DIR = unpack_if_missing("nfts")
ASSETS_DIR = unpack_if_missing("server_assets")

# Подпапки активов (они внутри server_assets, так что просто строим пути)
ASSETS_BANNERS_DIR = os.path.join(ASSETS_DIR, "banners")
ASSETS_RAMS_DIR = os.path.join(ASSETS_DIR, "rams")
ASSETS_CHAT_BG_DIR = os.path.join(ASSETS_DIR, "chat_backgrounds")
ASSETS_BOT_AVATAR_DIR = os.path.join(ASSETS_DIR, "bot_avatar")

# Создаем подпапки, если их вдруг нет (на случай пустой server_assets)
for d in [ASSETS_BANNERS_DIR, ASSETS_RAMS_DIR, ASSETS_CHAT_BG_DIR, ASSETS_BOT_AVATAR_DIR]:
    if not os.path.exists(d):
        try: os.makedirs(d)
        except: pass

# EMAIL CONFIG
SMTP_EMAIL = "russkihdmitrij869@gmail.com"
SMTP_PASSWORD = "ddkl ppug wlir zzgy"