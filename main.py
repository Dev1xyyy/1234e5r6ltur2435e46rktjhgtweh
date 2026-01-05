import socket
import threading
import time
import flet as ft
import json
import struct
import server_config as cfg
import server_state as state
import server_utils as utils
import server_db as db_mod
import server_logic as logic
from server_logger import logger, attach_gui_logger
from server_voice import voice_server

# --- ADMIN PANEL COLORS ---
C_BG = "#313338"
C_SIDE = "#2b2d31"
C_ITEM = "#232428"
C_PRIM = "#5865F2"
C_RED = "#DA373C"
C_GREEN = "#23A559"
C_TEXT = "#DBDEE1"

def handle_client(conn, addr):
    current_user_id = None
    logger.info(f"New connection from {addr}")
    try:
        while True:
            req = utils.recv_json(conn)
            if not req: break
            
            if req.get('action') == 'connect_user':
                current_user_id = req['payload']['id']
                with state.clients_lock:
                    state.connected_clients[current_user_id] = conn
                    state.online_users.add(current_user_id)
                
                utils.send_json(conn, {"status": "ok", "msg": "Connected"})
                
                # Notify everyone else that I am online
                utils.broadcast_all({"event": "user_status", "user_id": current_user_id, "status": "online"})
                
                # Send me the list of everyone who is ALREADY online
                with state.clients_lock:
                    for online_uid in state.online_users:
                        if online_uid != current_user_id:
                            utils.send_json(conn, {"event": "user_status", "user_id": online_uid, "status": "online"})
                
                logger.info(f"User {current_user_id} connected")
                continue
            
            response = logic.process_request(req)
            utils.send_json(conn, response)
    except Exception as e:
        logger.error(f"Error handling client {addr}: {e}")
    finally:
        if current_user_id:
            voice_server.leave_channel(current_user_id)
            
            with state.clients_lock:
                if current_user_id in state.connected_clients: 
                    del state.connected_clients[current_user_id]
                if current_user_id in state.online_users: 
                    state.online_users.remove(current_user_id)
            utils.broadcast_all({"event": "user_status", "user_id": current_user_id, "status": "offline"})
            logger.info(f"User {current_user_id} disconnected")
        conn.close()

def run_server_core():
    """Основной цикл сервера (запускается в потоке)"""
    try:
        db_mod.init_db()
        voice_server.start()
        
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((cfg.HOST, cfg.PORT))
        server.listen()
        logger.info(f"Сервер NovCord запущен на {cfg.HOST}:{cfg.PORT}")
        
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr)).start()
    except Exception as e:
        logger.critical(f"Server crash: {e}")

# --- ADMIN API HELPER ---
def send_cmd(req):
    """Отправка команд локальному серверу для админки"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(('127.0.0.1', cfg.PORT))
        msg = json.dumps(req).encode('utf-8')
        s.sendall(struct.pack('>I', len(msg)) + msg)
        
        def recvall(sock, n):
            data = bytearray()
            while len(data) < n:
                packet = sock.recv(n - len(data))
                if not packet: return None
                data.extend(packet)
            return data

        raw_len = recvall(s, 4)
        if not raw_len: return {"status": "error", "msg": "No response"}
        msglen = struct.unpack('>I', raw_len)[0]
        data = recvall(s, msglen)
        s.close()
        return json.loads(data.decode('utf-8'))
    except Exception as e:
        return {"status": "error", "msg": str(e)}

def main(page: ft.Page):
    page.title = "NovCord Server Manager & Admin Panel"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = C_BG
    page.padding = 0
    # Адаптация под размеры окна (минимальные)
    page.window.min_width = 1000
    page.window.min_height = 700
    page.window.width = 1200
    page.window.height = 800

    # --- TAB 1: SERVER CONSOLE & STATS ---
    
    log_list = ft.ListView(expand=True, spacing=2, auto_scroll=True, padding=10)
    
    def log_callback(record):
        color = "white"
        if record.levelno == 20: color = "#23a559"
        elif record.levelno == 30: color = "orange"
        elif record.levelno >= 40: color = "#da373c"
        
        msg = f"[{record.asctime}] {record.levelname}: {record.getMessage()}"
        log_list.controls.append(ft.Text(msg, color=color, font_family="Consolas, monospace", size=12, selectable=True))
        if len(log_list.controls) > 500: log_list.controls.pop(0)
        page.update()

    attach_gui_logger(log_callback)

    stat_online = ft.Text("0", size=20, weight="bold", color="#23a559")
    stat_uptime = ft.Text("0:00", size=20, weight="bold", color="white")
    start_time = time.time()

    def update_stats():
        while True:
            stat_online.value = str(len(state.online_users))
            uptime_sec = int(time.time() - start_time)
            mins, secs = divmod(uptime_sec, 60)
            hours, mins = divmod(mins, 60)
            stat_uptime.value = f"{hours:02}:{mins:02}:{secs:02}"
            try: page.update()
            except: pass
            time.sleep(1)

    sidebar = ft.Container(
        width=250,
        bgcolor="#2b2d31",
        padding=20,
        content=ft.Column([
            ft.Text("NovCord Server", size=24, weight="bold", color="#5865F2"),
            ft.Divider(),
            ft.Text("Статус", size=12, color="grey"),
            ft.Container(bgcolor="#1e1f22", padding=10, border_radius=5, content=ft.Row([ft.Icon(ft.icons.CIRCLE, color="#23a559", size=14), ft.Text("ONLINE", color="#23a559", weight="bold")])),
            ft.Container(height=10),
            ft.Text("Онлайн", size=12, color="grey"),
            ft.Container(bgcolor="#1e1f22", padding=10, border_radius=5, content=ft.Row([ft.Icon(ft.icons.PEOPLE), stat_online])),
            ft.Container(height=10),
            ft.Text("Аптайм", size=12, color="grey"),
            ft.Container(bgcolor="#1e1f22", padding=10, border_radius=5, content=ft.Row([ft.Icon(ft.icons.TIMER), stat_uptime])),
            ft.Divider(),
            ft.Text("Инфо", size=16, weight="bold"),
            ft.Text(f"Host: {cfg.HOST}", size=12),
            ft.Text(f"Port: {cfg.PORT}", size=12),
            ft.Text(f"Voice: {cfg.VOICE_PORT}", size=12),
            ft.Container(expand=True),
            ft.ElevatedButton("Очистить лог", icon=ft.icons.CLEANING_SERVICES, bgcolor="#4e5058", color="white", on_click=lambda e: (log_list.controls.clear(), page.update()))
        ])
    )

    console_tab = ft.Row([
        sidebar,
        ft.Column([
            ft.Container(padding=10, content=ft.Text("Server Console", weight="bold", size=16)),
            ft.Container(content=log_list, expand=True, bgcolor="black", border=ft.border.all(1, "#2b2d31"), border_radius=8, margin=10)
        ], expand=True, spacing=0)
    ], expand=True, spacing=0)

    # --- TAB 2: ADMIN PANEL ---
    
    all_users = []
    adm_stat_total = ft.Text("0", size=30, weight="bold", color=C_PRIM)
    adm_stat_banned = ft.Text("0", size=30, weight="bold", color=C_RED)
    adm_stat_admins = ft.Text("0", size=30, weight="bold", color=C_GREEN)
    users_view = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    def update_adm_stats():
        adm_stat_total.value = str(len(all_users))
        adm_stat_banned.value = str(len([u for u in all_users if u.get('blocked')]))
        adm_stat_admins.value = str(len([u for u in all_users if u.get('is_admin')]))
        page.update()

    def open_actions(u):
        is_banned = u.get('blocked', 0) == 1
        tabs = ft.Tabs(selected_index=0)
        
        # TAB 1: Safety
        reason_tf = ft.TextField(label="Причина бана")
        def do_ban(e):
            act = "admin_unban_user" if is_banned else "admin_ban_user"
            send_cmd({"action": act, "payload": {"target_id": u['id'], "reason": reason_tf.value}})
            page.close(dlg); load_data()

        tab_safety = ft.Container(padding=10, content=ft.Column([
            ft.Text(f"Статус: {'Забанен' if is_banned else 'Активен'}", color=C_RED if is_banned else C_GREEN),
            ft.Divider(),
            reason_tf if not is_banned else ft.Container(),
            ft.ElevatedButton("Разбанить" if is_banned else "Забанить", bgcolor=C_GREEN if is_banned else C_RED, color="white", on_click=do_ban)
        ]))

        # TAB 2: Edit
        new_name = ft.TextField(label="Новый Username", value=u['tag'].split('#')[0])
        new_about = ft.TextField(label="Обо мне", value="Изменено администратором")
        def do_edit(e):
            payload = {"id": u['id'], "username": new_name.value, "about": new_about.value, "custom_status": "", "banner": "black", "nickname_color": "white"}
            res = send_cmd({"action": "update_profile", "payload": payload})
            if res.get('status') == 'ok': page.snack_bar = ft.SnackBar(ft.Text("Профиль изменен"), bgcolor=C_GREEN); page.snack_bar.open=True; page.close(dlg); load_data()
        
        tab_edit = ft.Container(padding=10, content=ft.Column([
            ft.Text("Редактирование", weight="bold"), new_name, new_about,
            ft.ElevatedButton("Сохранить", on_click=do_edit)
        ]))

        # TAB 3: Message
        msg_tf = ft.TextField(label="Сообщение", multiline=True)
        def send_dm(e):
            if not msg_tf.value: return
            send_cmd({"action": "send_msg", "payload": {"sender": 0, "target": u['id'], "type": "private", "text": f"[ADMIN]: {msg_tf.value}"}}) # Sender 0 is bot
            msg_tf.value = "Отправлено!"; msg_tf.update()
        
        tab_msg = ft.Container(padding=10, content=ft.Column([
            ft.Text("Отправить ЛС от бота", size=12, color="grey"), msg_tf,
            ft.ElevatedButton("Отправить", on_click=send_dm)
        ]))

        # TAB 4: Units
        units_tf = ft.TextField(label="Количество", value="100")
        def add_units(e):
            try:
                amt = int(units_tf.value)
                send_cmd({"action": "admin_add_units", "payload": {"target_id": u['id'], "amount": amt}})
                page.close(dlg)
            except: pass
        
        tab_units = ft.Container(padding=10, content=ft.Column([ft.Text("Units", weight="bold"), units_tf, ft.ElevatedButton("Начислить", on_click=add_units)]))

        tabs.tabs = [
            ft.Tab(text="Безопасность", content=tab_safety),
            ft.Tab(text="Профиль", content=tab_edit),
            ft.Tab(text="ЛС", content=tab_msg),
            ft.Tab(text="Units", content=tab_units)
        ]
        
        dlg = ft.AlertDialog(title=ft.Text(f"Управление: {u['tag']}"), content=ft.Container(width=500, height=450, content=tabs), actions=[ft.TextButton("Закрыть", on_click=lambda _: page.close(dlg))])
        page.overlay.append(dlg); dlg.open=True; page.update()

    def render_list(users):
        users_view.controls.clear()
        for u in users:
            is_banned = u.get('blocked', 0) == 1
            is_admin = u.get('is_admin', 0) == 1
            card = ft.Container(
                bgcolor=C_SIDE, padding=10, border_radius=5,
                content=ft.Row([
                    ft.Row([
                        ft.CircleAvatar(content=ft.Text(u['tag'][0]), bgcolor=C_PRIM),
                        ft.Column([ft.Text(u['tag'], weight="bold"), ft.Text(u['email'], size=12, color="grey")], spacing=2)
                    ]),
                    ft.Row([
                         ft.Container(padding=5, border_radius=5, bgcolor=C_PRIM if is_admin else "transparent", content=ft.Text("ADMIN", size=10)) if is_admin else ft.Container(),
                         ft.Container(padding=5, border_radius=5, bgcolor=C_RED if is_banned else C_GREEN, content=ft.Text("BANNED" if is_banned else "ACTIVE", size=10)),
                         ft.IconButton(ft.icons.EDIT, on_click=lambda e, u=u: open_actions(u))
                    ])
                ], alignment="spaceBetween")
            )
            users_view.controls.append(card)
        users_view.update()

    def load_data(e=None):
        users_view.controls.clear()
        # Need to wait for server to start if running first time
        try:
            res = send_cmd({"action": "admin_get_all_users", "payload": {}})
            if res.get('status') == 'ok':
                all_users.clear(); all_users.extend(res['users']); update_adm_stats(); render_list(all_users)
            else:
                users_view.controls.append(ft.Text("Ошибка подключения к API сервера", color="red"))
                users_view.update()
        except:
            users_view.controls.append(ft.Text("Сервер еще не готов...", color="orange"))
            users_view.update()

    search_bar = ft.TextField(hint_text="Поиск пользователя...", bgcolor=C_SIDE, border_radius=10, expand=True, on_change=lambda e: render_list([u for u in all_users if e.control.value.lower() in u['tag'].lower()]))

    # Broadcast Tab
    broadcast_tf = ft.TextField(label="Сообщение для рассылки", multiline=True)
    def send_broadcast(e):
        res = send_cmd({"action": "admin_broadcast_msg", "payload": {"text": broadcast_tf.value}})
        if res.get('status') == 'ok': page.snack_bar = ft.SnackBar(ft.Text("Рассылка отправлена!"), bgcolor=C_GREEN); page.snack_bar.open=True; page.update()

    broadcast_view = ft.Container(padding=20, content=ft.Column([
        ft.Text("Рассылка от системного бота", size=20, weight="bold"), broadcast_tf,
        ft.ElevatedButton("Отправить всем", on_click=send_broadcast, bgcolor=C_PRIM, color="white")
    ]))

    admin_tabs = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(text="Пользователи", content=ft.Column([
                ft.Row([
                    ft.Container(bgcolor=C_SIDE, padding=20, border_radius=10, expand=True, content=ft.Column([ft.Text("Всего"), adm_stat_total])),
                    ft.Container(bgcolor=C_SIDE, padding=20, border_radius=10, expand=True, content=ft.Column([ft.Text("Забанено"), adm_stat_banned])),
                    ft.Container(bgcolor=C_SIDE, padding=20, border_radius=10, expand=True, content=ft.Column([ft.Text("Админы"), adm_stat_admins])),
                ]),
                ft.Divider(),
                ft.Row([search_bar, ft.IconButton(ft.icons.REFRESH, on_click=load_data)]),
                users_view
            ], expand=True)),
            ft.Tab(text="Рассылка", content=broadcast_view)
        ], expand=True
    )

    admin_tab = ft.Container(padding=20, content=admin_tabs)

    # --- MAIN NAVIGATION ---
    
    tabs = ft.Tabs(
        selected_index=0,
        animation_duration=300,
        tabs=[
            ft.Tab(text="Сервер", icon=ft.icons.TERMINAL, content=console_tab),
            ft.Tab(text="Администрирование", icon=ft.icons.ADMIN_PANEL_SETTINGS, content=admin_tab)
        ],
        expand=True
    )

    page.add(tabs)

    # Start Server Logic in Background Thread
    threading.Thread(target=run_server_core, daemon=True).start()
    
    # Start Stats Updater
    threading.Thread(target=update_stats, daemon=True).start()
    
    # Delayed initial load for admin data (give server time to bind)
    def delayed_load():
        time.sleep(2)
        load_data()
    threading.Thread(target=delayed_load, daemon=True).start()

if __name__ == "__main__":
    ft.app(target=main)