import subprocess
import sys
import platform

def install(package):
    """Устанавливает пакет через pip"""
    print(f"[INFO] Установка {package}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"[OK] {package} успешно установлен.\n")
    except subprocess.CalledProcessError:
        print(f"[ERROR] Не удалось установить {package}.\n")

def main():
    print("--- Установка зависимостей для сервера NovCord ---\n")
    
    # Список библиотек
    requirements = [
        "flet",          # GUI оболочка
        "pyaudio",       # Голосовая связь
        "pyinstaller",   # Сборка в exe
        # Стандартные библиотеки (socket, threading, sqlite3) встроены в Python
    ]

    # Проверка на Windows для PyAudio (иногда требует wheel)
    if platform.system() == "Windows":
        print("[INFO] Проверка окружения Windows...")
        # PyAudio на Windows обычно ставится нормально через pip,
        # но если нет C++ компиляторов, pip попробует найти wheel.
        # Если будет ошибка с PyAudio, пользователю нужно будет скачать whl вручную.

    for lib in requirements:
        install(lib)

    print("--- Установка завершена! ---")

if __name__ == "__main__":
    main()