import logging
import os
from logging.handlers import RotatingFileHandler
import server_config as cfg

# Директория создается в config, здесь просто используем путь
log_file_path = os.path.join(cfg.LOG_DIR, "server.log")

class GuiHandler(logging.Handler):
    """Кастомный обработчик для отправки логов в GUI"""
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            self.callback(record)
        except Exception:
            self.handleError(record)

def setup_logger():
    """Настраивает логгер для сервера"""
    logger = logging.getLogger("NovCordServer")
    logger.setLevel(logging.INFO)
    
    # Форматтер
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Файловый хендлер
    try:
        file_handler = RotatingFileHandler(
            log_file_path, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Failed to setup file logging: {e}")
    
    # Консольный хендлер
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logger()

def attach_gui_logger(callback):
    """Подключает GUI к системе логирования"""
    gui_handler = GuiHandler(callback)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
    gui_handler.setFormatter(formatter)
    logger.addHandler(gui_handler)