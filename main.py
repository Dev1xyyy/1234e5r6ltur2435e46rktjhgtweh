import sys
import subprocess
import importlib.util
import socket
import threading

# --- 1. AUTO-INSTALL DEPENDENCIES ---
def check_and_install_dependencies():
    """
    Проверяет и устанавливает необходимые библиотеки перед запуском.
    """
    # Словарь: 'имя_модуля_в_коде': 'имя_пакета_в_pip'
    # На данный момент сервер использует стандартные библиотеки Python.
    # Если вы добавите PyAudio или другие либы на сервер, раскомментируйте строки ниже.
    required_libs = {
        # "pyaudio": "pyaudio", 
        # "requests": "requests",
    }

    print("--- Проверка зависимостей сервера ---")
    installed_any = False
    
    for module_name, package_name in required_libs.items():
        if importlib.util.find_spec(module_name) is None:
            print(f"[INSTALL] Библиотека '{package_name}' не найдена. Установка...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
                print(f"[OK] '{package_name}' успешно установлена.")
                installed_any = True
            except subprocess.CalledProcessError:
                print(f"[ERROR] Не удалось установить '{package_name}'.")
                print("Попробуйте установить вручную: pip install " + package_name)
        else:
            # print(f"[OK] '{package_name}' уже установлена.")
            pass
            
    if installed_any:
        print("--- Все зависимости установлены. Запуск... ---\n")
    else:
        print("--- Зависимости в порядке. Запуск... ---\n")

# Запускаем проверку перед импортом остальных модулей
check_and_install_dependencies()

# --- 2. SERVER IMPORTS ---
import server_config as cfg
import server_state as state
import server_utils as utils
import server_db as db_mod
import server_logic as logic
from server_logger import logger
from server_voice import voice_server

# --- 3. SERVER LOGIC ---

def handle_client(conn, addr):
    """Обработка подключения клиента"""
    current_user_id = None
    logger.info(f"New connection from {addr}")
    
    try:
        while True:
            req = utils.recv_json(conn)
            if not req: break
            
            # Специальная обработка для первичного подключения
            if req.get('action') == 'connect_user':
                current_user_id = req['payload']['id']
                with state.clients_lock:
                    state.connected_clients[current_user_id] = conn
                    state.online_users.add(current_user_id)
                
                utils.send_json(conn, {"status": "ok", "msg": "Connected"})
                
                # Уведомляем всех, что я онлайн
                utils.broadcast_all({"event": "user_status", "user_id": current_user_id, "status": "online"})
                
                # Отправляем мне список тех, кто УЖЕ онлайн
                with state.clients_lock:
                    for online_uid in state.online_users:
                        if online_uid != current_user_id:
                            utils.send_json(conn, {"event": "user_status", "user_id": online_uid, "status": "online"})
                
                logger.info(f"User {current_user_id} connected")
                continue
            
            # Обработка остальных запросов
            response = logic.process_request(req)
            utils.send_json(conn, response)
            
    except Exception as e:
        logger.error(f"Error handling client {addr}: {e}")
    finally:
        # Очистка при отключении
        if current_user_id:
            # Выход из голосового канала
            voice_server.leave_channel(current_user_id)
            
            with state.clients_lock:
                if current_user_id in state.connected_clients: 
                    del state.connected_clients[current_user_id]
                if current_user_id in state.online_users: 
                    state.online_users.remove(current_user_id)
            
            # Уведомление об оффлайне
            utils.broadcast_all({"event": "user_status", "user_id": current_user_id, "status": "offline"})
            logger.info(f"User {current_user_id} disconnected")
        
        conn.close()

def start_server():
    """Запуск основного цикла сервера"""
    
    # Инициализация ресурсов
    cfg.unpack_if_missing("server_files") # Убедимся, что папки существуют (если логика из server_config используется)
    
    db_mod.init_db()
    voice_server.start()
    
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind((cfg.HOST, cfg.PORT))
    except OSError as e:
        print(f"\n[CRITICAL ERROR] Не удалось запустить сервер на порту {cfg.PORT}.")
        print(f"Причина: {e}")
        print("Возможно, сервер уже запущен или порт занят другим приложением.")
        input("Нажмите Enter для выхода...")
        sys.exit(1)
        
    server.listen()
    
    start_msg = f"""
    =========================================
       NovCord Server Started Successfully
    =========================================
    IP: {cfg.HOST}
    TCP Port: {cfg.PORT}
    UDP Voice Port: {cfg.VOICE_PORT}
    Database: {cfg.DB_NAME}
    =========================================
    Logs are being written to logs/server.log
    Waiting for connections...
    """
    print(start_msg)
    logger.info(f"Сервер NovCord запущен на {cfg.HOST}:{cfg.PORT}")
    
    try:
        while True:
            conn, addr = server.accept()
            # Запускаем обработку клиента в отдельном потоке
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\n[INFO] Stopping server...")
    except Exception as e:
        logger.critical(f"Server main loop crash: {e}")
        print(f"[CRITICAL] Server crashed: {e}")
    finally:
        server.close()

if __name__ == "__main__":
    start_server()
