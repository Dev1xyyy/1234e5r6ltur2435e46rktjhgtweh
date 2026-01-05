import threading

db_lock = threading.Lock()
clients_lock = threading.Lock()
connected_clients = {}
online_users = set()