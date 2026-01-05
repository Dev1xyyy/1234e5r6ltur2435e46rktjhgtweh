import sqlite3
from datetime import datetime
import server_config as cfg
import server_state as state

def init_db():
    with state.db_lock:
        conn = sqlite3.connect(cfg.DB_NAME)
        cur = conn.cursor()
        
        # Основные таблицы
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            username TEXT,
            discriminator TEXT,
            password_hash TEXT,
            is_verified INTEGER DEFAULT 0,
            verification_code TEXT,
            avatar_color TEXT,
            avatar_image TEXT,
            avatar_decoration TEXT,
            banner_color TEXT DEFAULT 'black',
            banner_image TEXT,
            about_me TEXT DEFAULT 'Новичок',
            custom_status TEXT DEFAULT '',
            nickname_color TEXT DEFAULT 'white',
            is_blocked INTEGER DEFAULT 0,
            ban_reason TEXT DEFAULT '',
            is_admin INTEGER DEFAULT 0,
            chat_bg TEXT,
            units INTEGER DEFAULT 0,
            profile_music TEXT,
            created_at TEXT
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS friends (user_id INTEGER, friend_id INTEGER, status TEXT, PRIMARY KEY (user_id, friend_id))''')
        cur.execute('''CREATE TABLE IF NOT EXISTS user_blocks (user_id INTEGER, blocked_id INTEGER, PRIMARY KEY (user_id, blocked_id))''')
        cur.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER, target_id INTEGER, target_type TEXT,
            content TEXT, timestamp TEXT, reply_to_id INTEGER, is_edited INTEGER DEFAULT 0,
            attachment_type TEXT, attachment_filename TEXT, reactions TEXT DEFAULT '{}',
            status TEXT DEFAULT 'sent',
            forward_from_id INTEGER
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS message_reads (
            message_id INTEGER,
            user_id INTEGER,
            read_at TEXT,
            PRIMARY KEY (message_id, user_id)
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, owner_id INTEGER, avatar_color TEXT, avatar_image TEXT, banner_image TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS group_members (group_id INTEGER, user_id INTEGER, PRIMARY KEY (group_id, user_id))''')
        cur.execute('''CREATE TABLE IF NOT EXISTS group_blacklist (group_id INTEGER, user_id INTEGER, PRIMARY KEY (group_id, user_id))''')
        
        cur.execute('''CREATE TABLE IF NOT EXISTS nfts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            filename TEXT,
            name TEXT,
            minted_at TEXT,
            is_hidden INTEGER DEFAULT 0
        )''')

        # АВТОМИГРАЦИИ
        def add_column(table, column, type_def):
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_def}")
            except sqlite3.OperationalError:
                pass

        add_column("groups", "banner_image", "TEXT")
        add_column("nfts", "is_hidden", "INTEGER DEFAULT 0")
        add_column("users", "chat_bg", "TEXT")
        add_column("users", "units", "INTEGER DEFAULT 0")
        add_column("users", "profile_music", "TEXT")
        add_column("messages", "status", "TEXT DEFAULT 'sent'")
        add_column("messages", "forward_from_id", "INTEGER")
        
        # SYSTEM BOT CREATION (ID 0)
        try:
            cur.execute("INSERT OR IGNORE INTO users (id, email, username, discriminator, password_hash, is_verified, about_me, nickname_color, avatar_color, created_at) VALUES (0, 'bot@novcord.sys', 'NovCord', '0000', 'sys', 1, 'Это официальный бот NovCord', '#5865F2', '#5865F2', ?)", (str(datetime.now()),))
        except: pass

        conn.commit()
        conn.close()