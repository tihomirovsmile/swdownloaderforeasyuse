import tkinter as tk
from tkinter import ttk, messagebox
import threading
import requests
import webbrowser
import os
import subprocess
import shutil
import zipfile
import datetime
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageTk
import urllib.parse

# ---------- Конфигурация ----------
BASE_DIR = Path(__file__).parent if '__file__' in dir() else Path.cwd()
DOWNLOAD_DIR = BASE_DIR / "workshop_downloads"
STEAMCMD_DIR = BASE_DIR / "steamcmd"
STEAMCMD_EXE = STEAMCMD_DIR / "steamcmd.exe"
LOG_FILE = BASE_DIR / "steamcmd.log"
STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
STEAMAPI_BASE = "https://api.steampowered.com"

# ---------- Логирование ----------
def log_message(message: str, level: str = "INFO"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {message}"
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        log.write(line + "\n")

# ---------- Установка SteamCMD ----------
def ensure_steamcmd_installed():
    if STEAMCMD_EXE.exists():
        return True
    log_message("SteamCMD не найден. Начинаю загрузку...", "WARN")
    STEAMCMD_DIR.mkdir(parents=True, exist_ok=True)
    steamcmd_zip = STEAMCMD_DIR / "steamcmd.zip"
    try:
        r = requests.get(STEAMCMD_URL, stream=True, timeout=60)
        r.raise_for_status()
        with open(steamcmd_zip, 'wb') as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        with zipfile.ZipFile(steamcmd_zip, 'r') as zf:
            zf.extractall(STEAMCMD_DIR)
        os.remove(steamcmd_zip)
        log_message("SteamCMD успешно установлен.")
        return STEAMCMD_EXE.exists()
    except Exception as e:
        log_message(f"Ошибка установки SteamCMD: {e}", "ERROR")
        return False

# ---------- API информации о моде ----------
def fetch_mod_details(app_id: str, mod_id: str) -> dict | None:
    url = f"{STEAMAPI_BASE}/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    data = {"itemcount": "1", "publishedfileids[0]": mod_id}
    try:
        resp = requests.post(url, data=data, timeout=10)
        resp.raise_for_status()
        j = resp.json()
        details = j["response"]["publishedfiledetails"][0]
        if details.get("result") != 1:
            return None
        return {
            "id": details["publishedfileid"],
            "title": details.get("title", "Без названия"),
            "creator_id": details.get("creator", ""),
            "preview_url": details.get("preview_url", ""),
            "steam_url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={details['publishedfileid']}"
        }
    except Exception as e:
        log_message(f"Ошибка получения данных мода: {e}", "ERROR")
        return None

def make_safe_folder_name(title: str) -> str:
    safe = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in title)
    safe = safe.replace(' ', '_')
    while '__' in safe:
        safe = safe.replace('__', '_')
    return safe.strip('_')[:100]

# ---------- Скачивание ----------
def download_thread(app_id, mod_id, folder_name, callback):
    workshop_path = STEAMCMD_DIR / "steamapps" / "workshop" / "content" / app_id / mod_id
    if workshop_path.exists():
        shutil.rmtree(workshop_path)

    command = [
        str(STEAMCMD_EXE),
        "+@sSteamCmdForcePlatformType windows",
        "+force_install_dir", str(STEAMCMD_DIR),
        "+login", "anonymous",
        "+workshop_download_item", app_id, mod_id,
        "+quit"
    ]

    log_message(f"Запуск SteamCMD (AppID: {app_id}): {' '.join(command)}", "DEBUG")
    try:
        proc = subprocess.run(command, cwd=str(STEAMCMD_DIR), capture_output=True, text=True, timeout=300)
        stdout = proc.stdout
        stderr = proc.stderr
        log_message(f"SteamCMD stdout:\n{stdout}", "DEBUG")
        if stderr:
            log_message(f"SteamCMD stderr:\n{stderr}", "DEBUG")

        if "ERROR!" in stdout or "ERROR!" in stderr or proc.returncode != 0:
            if "caller chunk indicies out of date" in stdout:
                log_message("Сбой загрузки чанков.", "ERROR")
            elif "No subscription" in stdout:
                log_message("Мод требует подписки.", "ERROR")
            else:
                log_message(f"Ошибка SteamCMD (код {proc.returncode}).", "ERROR")
            callback(False, "Не удалось скачать мод по техническим причинам.\nПодробности в лог-файле.")
            return

        if not workshop_path.exists() or not any(workshop_path.iterdir()):
            log_message("Папка с модом пуста.", "ERROR")
            callback(False, "Файлы мода не получены.")
            return

        target_path = DOWNLOAD_DIR / folder_name
        if target_path.exists():
            shutil.rmtree(target_path)
        shutil.copytree(workshop_path, target_path)
        shutil.rmtree(workshop_path, ignore_errors=True)
        log_message(f"Мод сохранён в {target_path}")
        callback(True, f"Мод успешно сохранён в:\n{target_path}")
    except subprocess.TimeoutExpired:
        log_message("Таймаут скачивания.", "ERROR")
        callback(False, "Превышено время ожидания (5 минут).")
    except Exception as e:
        log_message(f"Непредвиденная ошибка: {e}", "ERROR")
        callback(False, "Внутренняя ошибка приложения.")

# ---------- GUI ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Steam Workshop Downloader")
        self.geometry("820x700")
        self.minsize(750, 650)
        self.configure(bg="#1e1e1e")

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TProgressbar", thickness=8, troughcolor='#2d2d2d', background='#e05a3c')

        # Шапка
        header = tk.Frame(self, bg="#e05a3c", height=50)
        header.pack(fill=tk.X)
        tk.Label(header, text="STEAM WORKSHOP DOWNLOADER", font=("Segoe UI", 14, "bold"),
                 fg="white", bg="#e05a3c").pack(pady=10)

        main_frame = tk.Frame(self, bg="#1e1e1e")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        # ---------- Блок выбора игры ----------
        app_frame = tk.LabelFrame(main_frame, text="Игра (Steam AppID)", fg="#cccccc", bg="#1e1e1e",
                                  font=("Segoe UI", 9, "bold"), padx=10, pady=10)
        app_frame.pack(fill=tk.X, pady=(0,10))

        tk.Label(app_frame, text="Поиск игры:", fg="white", bg="#1e1e1e", font=("Segoe UI", 9)).grid(row=0, column=0, padx=5, sticky="e")
        self.game_search_var = tk.StringVar()
        self.game_search_entry = tk.Entry(app_frame, textvariable=self.game_search_var, width=25, font=("Segoe UI", 10),
                                          bg="#2d2d2d", fg="white", insertbackground="white")
        self.game_search_entry.grid(row=0, column=1, padx=5)
        self.game_search_btn = tk.Button(app_frame, text="🔍 Найти игру (в браузере)", command=self.search_game_browser,
                                         bg="#e05a3c", fg="white", font=("Segoe UI", 9), relief=tk.FLAT)
        self.game_search_btn.grid(row=0, column=2, padx=5)

        tk.Label(app_frame, text="AppID:", fg="white", bg="#1e1e1e", font=("Segoe UI", 9)).grid(row=1, column=0, padx=5, sticky="e", pady=(10,0))
        self.appid_entry = tk.Entry(app_frame, width=10, font=("Segoe UI", 11), bg="#2d2d2d", fg="white", insertbackground="white")
        self.appid_entry.grid(row=1, column=1, padx=5, pady=(10,0))
        self.appid_entry.insert(0, "1118200")

        tk.Label(app_frame, text="Популярные:", fg="#aaaaaa", bg="#1e1e1e", font=("Segoe UI", 8)).grid(row=1, column=2, padx=(15,5), pady=(10,0))
        self.preset_var = tk.StringVar()
        presets = {"People Playground": "1118200", "Garry's Mod": "4000", "Cities: Skylines": "255710",
                   "RimWorld": "294100", "Wallpaper Engine": "431960"}
        self.preset_combo = ttk.Combobox(app_frame, textvariable=self.preset_var, values=list(presets.keys()),
                                         state="readonly", width=20)
        self.preset_combo.grid(row=1, column=3, padx=5, pady=(10,0))
        self.preset_combo.bind("<<ComboboxSelected>>", lambda e: self.appid_entry.delete(0, tk.END) or
                                                         self.appid_entry.insert(0, presets[self.preset_var.get()]))

        # ---------- Блок поиска мода ----------
        mod_frame = tk.LabelFrame(main_frame, text="Мод (Workshop ID)", fg="#cccccc", bg="#1e1e1e",
                                  font=("Segoe UI", 9, "bold"), padx=10, pady=10)
        mod_frame.pack(fill=tk.X, pady=(0,10))

        tk.Label(mod_frame, text="Поиск мода:", fg="white", bg="#1e1e1e", font=("Segoe UI", 9)).grid(row=0, column=0, padx=5, sticky="e")
        self.mod_search_var = tk.StringVar()
        self.mod_search_entry = tk.Entry(mod_frame, textvariable=self.mod_search_var, width=25, font=("Segoe UI", 10),
                                         bg="#2d2d2d", fg="white", insertbackground="white")
        self.mod_search_entry.grid(row=0, column=1, padx=5)
        self.mod_search_btn = tk.Button(mod_frame, text="🔍 Искать моды (в браузере)", command=self.search_mods_browser,
                                        bg="#e05a3c", fg="white", font=("Segoe UI", 9), relief=tk.FLAT)
        self.mod_search_btn.grid(row=0, column=2, padx=5)

        tk.Label(mod_frame, text="Mod ID:", fg="white", bg="#1e1e1e", font=("Segoe UI", 9)).grid(row=1, column=0, padx=5, sticky="e", pady=(10,0))
        self.modid_entry = tk.Entry(mod_frame, width=25, font=("Segoe UI", 11), bg="#2d2d2d", fg="white", insertbackground="white")
        self.modid_entry.grid(row=1, column=1, padx=5, pady=(10,0))
        self.search_btn = tk.Button(mod_frame, text="📋 Инфо о моде", command=self.search_mod,
                                    bg="#e05a3c", fg="white", font=("Segoe UI", 10, "bold"), relief=tk.FLAT)
        self.search_btn.grid(row=1, column=2, padx=10, pady=(10,0))

        # ---------- Панель превью и информации ----------
        self.info_panel = tk.Frame(main_frame, bg="#1e1e1e")
        self.info_panel.pack(fill=tk.BOTH, expand=True)

        self.preview_frame = tk.Frame(self.info_panel, bg="#2d2d2d", width=200, height=150)
        self.preview_frame.pack(side=tk.LEFT, padx=(0,10), fill=tk.Y)
        self.preview_frame.pack_propagate(False)
        self.preview_label = tk.Label(self.preview_frame, bg="#2d2d2d", text="Нет превью", fg="#888888")
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        self.preview_label.bind("<Button-1>", lambda e: self.open_preview())
        self.preview_url = None

        info_text_frame = tk.Frame(self.info_panel, bg="#1e1e1e")
        info_text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.info_text = tk.StringVar(value="Введите AppID игры и ID мода, затем нажмите «Инфо о моде».")
        tk.Label(info_text_frame, textvariable=self.info_text, fg="white", bg="#1e1e1e",
                 font=("Segoe UI", 9), justify=tk.LEFT, wraplength=450).pack(anchor="nw")

        # ---------- Кнопки действий ----------
        btn_frame = tk.Frame(main_frame, bg="#1e1e1e")
        btn_frame.pack(fill=tk.X, pady=(10,0))
        self.steam_btn = tk.Button(btn_frame, text="🔗 Открыть в Steam", state=tk.DISABLED, command=self.open_steam,
                                   bg="#444", fg="white", font=("Segoe UI", 9), relief=tk.FLAT)
        self.steam_btn.pack(side=tk.LEFT, padx=2)
        self.author_btn = tk.Button(btn_frame, text="👤 Профиль автора", state=tk.DISABLED, command=self.open_author,
                                    bg="#444", fg="white", font=("Segoe UI", 9), relief=tk.FLAT)
        self.author_btn.pack(side=tk.LEFT, padx=2)
        self.download_btn = tk.Button(btn_frame, text="📥 Скачать мод", state=tk.DISABLED, command=self.download_mod,
                                      bg="#e05a3c", fg="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT)
        self.download_btn.pack(side=tk.LEFT, padx=2)
        self.log_btn = tk.Button(btn_frame, text="📄 Лог", command=self.open_log,
                                 bg="#555", fg="white", font=("Segoe UI", 9), relief=tk.FLAT)
        self.log_btn.pack(side=tk.LEFT, padx=2)
        self.folder_btn = tk.Button(btn_frame, text="📁 Загрузки", command=self.open_mods_folder,
                                    bg="#555", fg="white", font=("Segoe UI", 9), relief=tk.FLAT)
        self.folder_btn.pack(side=tk.LEFT, padx=2)

        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.pack(fill=tk.X, pady=(10,0))
        self.progress.pack_forget()

        self.status_var = tk.StringVar(value="Готов к работе")
        tk.Label(main_frame, textvariable=self.status_var, fg="#888888", bg="#1e1e1e",
                 font=("Segoe UI", 8)).pack(side=tk.BOTTOM, pady=5)

        self.current_mod = None

    # ---------- Вспомогательные методы ----------
    def set_status(self, text):
        self.status_var.set(text)

    def enable_buttons(self, enable=True):
        state = tk.NORMAL if enable else tk.DISABLED
        self.steam_btn.config(state=state)
        self.author_btn.config(state=state)
        self.download_btn.config(state=state)

    def load_preview_image(self, url):
        if not url:
            self.preview_label.config(image='', text="Нет превью")
            self.preview_url = None
            return
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content))
            img.thumbnail((200, 150), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self.preview_label.config(image=photo, text="")
            self.preview_label.image = photo
            self.preview_url = url
        except Exception:
            self.preview_label.config(image='', text="Не удалось\nзагрузить")
            self.preview_url = None

    # ---------- Поиск игры через браузер ----------
    def search_game_browser(self):
        query = self.game_search_var.get().strip()
        if not query:
            messagebox.showinfo("Поиск", "Введите название игры.")
            return
        url = f"https://store.steampowered.com/search/?term={urllib.parse.quote(query)}"
        webbrowser.open(url)
        self.set_status("Поиск игры открыт в браузере. Скопируйте AppID и вставьте в поле.")

    # ---------- Поиск модов через браузер ----------
    def search_mods_browser(self):
        query = self.mod_search_var.get().strip()
        app_id = self.appid_entry.get().strip()
        if not query:
            messagebox.showinfo("Поиск", "Введите название мода.")
            return
        if not app_id.isdigit():
            messagebox.showerror("Ошибка", "Сначала укажите AppID игры.")
            return
        url = f"https://steamcommunity.com/workshop/browse/?appid={app_id}&searchtext={urllib.parse.quote(query)}"
        webbrowser.open(url)
        self.set_status("Поиск модов открыт в браузере. Скопируйте ID мода и вставьте в поле.")

    # ---------- Информация о моде ----------
    def search_mod(self):
        app_id = self.appid_entry.get().strip()
        mod_id = self.modid_entry.get().strip()
        if not app_id.isdigit() or not mod_id.isdigit():
            messagebox.showerror("Ошибка", "AppID и Mod ID должны быть числами.")
            return
        self.set_status("Загрузка информации...")
        self.enable_buttons(False)
        self.search_btn.config(state=tk.DISABLED)
        self.progress.pack(fill=tk.X, pady=(10,0))
        self.progress.start()
        threading.Thread(target=self._fetch_and_display, args=(app_id, mod_id), daemon=True).start()

    def _fetch_and_display(self, app_id, mod_id):
        mod = fetch_mod_details(app_id, mod_id)
        self.progress.stop()
        self.progress.pack_forget()
        self.search_btn.config(state=tk.NORMAL)
        if mod:
            self.current_mod = mod
            info = (f"Название: {mod['title']}\n"
                    f"ID: {mod['id']}\n"
                    f"Автор ID: {mod['creator_id']}\n"
                    f"Ссылка: {mod['steam_url']}")
            self.info_text.set(info)
            self.load_preview_image(mod.get("preview_url"))
            self.enable_buttons(True)
            self.set_status("Информация загружена")
        else:
            self.info_text.set("Мод не найден или произошла ошибка.")
            self.current_mod = None
            self.load_preview_image(None)
            self.enable_buttons(False)
            self.set_status("Мод не найден")

    def open_preview(self):
        if self.preview_url:
            webbrowser.open(self.preview_url)

    def open_steam(self):
        if self.current_mod:
            webbrowser.open(self.current_mod["steam_url"])

    def open_author(self):
        if self.current_mod and self.current_mod["creator_id"]:
            webbrowser.open(f"https://steamcommunity.com/profiles/{self.current_mod['creator_id']}")

    def download_mod(self):
        if not self.current_mod:
            return
        app_id = self.appid_entry.get().strip()
        mod = self.current_mod
        dialog = tk.Toplevel(self)
        dialog.title("Имя папки")
        dialog.geometry("350x150")
        dialog.configure(bg="#2d2d2d")
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(dialog, text="Выберите имя папки:", fg="white", bg="#2d2d2d", font=("Segoe UI", 10)).pack(pady=10)
        choice = tk.StringVar(value="id")
        tk.Radiobutton(dialog, text=f"ID: {mod['id']}", variable=choice, value="id",
                       fg="white", bg="#2d2d2d", selectcolor="#2d2d2d", font=("Segoe UI", 9)).pack(anchor="w", padx=20)
        safe_name = make_safe_folder_name(mod['title'])
        tk.Radiobutton(dialog, text=f"Название: {safe_name}", variable=choice, value="name",
                       fg="white", bg="#2d2d2d", selectcolor="#2d2d2d", font=("Segoe UI", 9)).pack(anchor="w", padx=20)
        def confirm():
            dialog.destroy()
            folder_name = mod['id'] if choice.get() == "id" else safe_name
            self._start_download(app_id, mod['id'], folder_name)
        tk.Button(dialog, text="Скачать", command=confirm, bg="#e05a3c", fg="white",
                  font=("Segoe UI", 10, "bold"), padx=20).pack(pady=10)

    def _start_download(self, app_id, mod_id, folder_name):
        self.set_status("Скачивание...")
        self.progress.pack(fill=tk.X, pady=(10,0))
        self.progress.start()
        self.enable_buttons(False)
        self.search_btn.config(state=tk.DISABLED)
        threading.Thread(target=download_thread, args=(app_id, mod_id, folder_name, self._on_download_complete), daemon=True).start()

    def _on_download_complete(self, success, message):
        self.progress.stop()
        self.progress.pack_forget()
        self.enable_buttons(True)
        self.search_btn.config(state=tk.NORMAL)
        if success:
            messagebox.showinfo("Успех", message)
            self.set_status("Мод скачан")
        else:
            messagebox.showerror("Ошибка загрузки", message)
            self.set_status("Ошибка при скачивании")

    def open_log(self):
        if LOG_FILE.exists():
            os.startfile(LOG_FILE)
        else:
            messagebox.showinfo("Лог", "Лог-файл ещё не создан.")

    def open_mods_folder(self):
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(DOWNLOAD_DIR)

# ---------- Точка входа ----------
if __name__ == "__main__":
    if not ensure_steamcmd_installed():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Ошибка", "Не удалось установить SteamCMD.")
        exit(1)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    app = App()
    app.mainloop()
