import os
import subprocess
import sys

def build():
    # Убедимся, что PyInstaller установлен
    try:
        import PyInstaller
    except ImportError:
        print("Устанавливаю PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Параметры сборки
    script = "main.py"
    exe_name = "SteamWorkshopDownloader"

    # Основные параметры
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                # единый exe
        "--noconsole",              # без консольного окна
        f"--name={exe_name}",
        "--clean",
        "--add-data", "steamcmd.zip;.",  # добавим архив SteamCMD в сборку, чтобы не качать из интернета
        script
    ]

    # Можно также включить Pillow скрытым импортом
    cmd.insert(-1, "--hidden-import=PIL._tkinter_finder")

    print("Запуск сборки...")
    subprocess.check_call(cmd)

    print(f"\nГотово! Исполняемый файл находится в папке 'dist/{exe_name}.exe'")

if __name__ == "__main__":
    build()