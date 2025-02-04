#!/usr/bin/env python3
import sys, os, ctypes, time, threading, tempfile, requests, json, math, datetime, signal, sqlite3, shutil, csv
from collections import defaultdict
from queue import Queue
import tkinter as tk
import customtkinter as ctk
import keyboard
try:
    import sounddevice as sd
    import numpy as np
except ImportError:
    sd = None
    np = None
import mouse
try:
    import pyautogui
except ImportError:
    pyautogui = None
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
except ImportError:
    Image = ImageDraw = ImageFilter = ImageEnhance = None
import pystray

DATA_DIR = os.path.join(os.getcwd(), "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
CATEGORIES = ["keyboard", "mouse", "screentime", "words", "streaks", "misc"]
current_file_index = {cat: 0 for cat in CATEGORIES}
SIZE_LIMIT = 1 * 1024 * 1024
def get_data_file_path(category, index):
    return os.path.join(DATA_DIR, f"{category}_data_{index}.ndjson")
def append_record(category, record):
    global current_file_index
    index = current_file_index[category]
    file_path = get_data_file_path(category, index)
    if not os.path.exists(file_path):
        with open(file_path, "w") as f:
            pass
    if os.path.getsize(file_path) >= SIZE_LIMIT:
        index += 1
        current_file_index[category] = index
        file_path = get_data_file_path(category, index)
        with open(file_path, "w") as f:
            pass
    try:
        with open(file_path, "a") as f:
            f.write(json.dumps(record) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"Error writing to {file_path}: {e}")
def load_latest_record(category):
    files = []
    for filename in os.listdir(DATA_DIR):
        if filename.startswith(f"{category}_data_") and filename.endswith(".ndjson"):
            try:
                idx = int(filename[len(f"{category}_data_"):-7])
                files.append((idx, os.path.join(DATA_DIR, filename)))
            except Exception:
                continue
    if not files:
        return None
    files.sort(key=lambda x: x[0])
    last_file = files[-1][1]
    try:
        with open(last_file, "r") as f:
            lines = f.readlines()
            if lines:
                return json.loads(lines[-1])
    except Exception as e:
        print(f"error reading {os.path.basename(last_file)}: {e}")
    return None
def backup_data_folder():
    backup_dir = os.path.join(tempfile.gettempdir(), "klogger_data")
    if not os.path.exists(backup_dir):
        try:
            os.makedirs(backup_dir)
        except Exception as e:
            print(f"Error creating backup folder: {e}")
            return
    for filename in os.listdir(DATA_DIR):
        source = os.path.join(DATA_DIR, filename)
        dest = os.path.join(backup_dir, filename)
        try:
            shutil.copy2(source, dest)
        except Exception as e:
            print(f"Backup failed for {filename}: {e}")
def periodic_backup():
    backup_data_folder()
    safe_after(3600000, periodic_backup)
def sigint_handler(sig, frame):
    global app_running
    app_running = False
    try:
        root.destroy()
    except Exception:
        pass
    sys.exit(0)
signal.signal(signal.SIGINT, sigint_handler)

mouse_data = {}
mouse_click_positions = {"left": [], "right": [], "middle": []}
mouse_movements = []
class MouseStats:
    left_clicks = 0
    right_clicks = 0
    middle_clicks = 0
    scroll_count = 0
    total_distance = 0.0
    last_position = None
def update_mouse_data(event_type, value):
    today = time.strftime("%Y-%m-%d")
    if today not in mouse_data:
        mouse_data[today] = {"left": 0, "right": 0, "middle": 0, "scroll": 0, "distance": 0.0}
    if event_type == "left":
        mouse_data[today]["left"] += value
    elif event_type == "right":
        mouse_data[today]["right"] += value
    elif event_type == "middle":
        mouse_data[today]["middle"] += value
    elif event_type == "scroll":
        mouse_data[today]["scroll"] += value
    elif event_type == "distance":
        mouse_data[today]["distance"] += value
def handle_mouse_event(event):
    from mouse import MoveEvent, ButtonEvent, WheelEvent
    if isinstance(event, MoveEvent):
        mouse_movements.append((time.time(), event.x, event.y))
        if MouseStats.last_position is not None:
            dx = event.x - MouseStats.last_position[0]
            dy = event.y - MouseStats.last_position[1]
            dist = math.sqrt(dx*dx + dy*dy)
            MouseStats.total_distance += dist
            update_mouse_data("distance", dist)
        MouseStats.last_position = (event.x, event.y)
    elif isinstance(event, ButtonEvent):
        if event.event_type in ('down', 'double'):
            pos = mouse.get_position()
            if event.button == 'left':
                MouseStats.left_clicks += 1
                update_mouse_data("left", 1)
                mouse_click_positions["left"].append(pos)
            elif event.button == 'right':
                MouseStats.right_clicks += 1
                update_mouse_data("right", 1)
                mouse_click_positions["right"].append(pos)
            elif event.button == 'middle':
                MouseStats.middle_clicks += 1
                update_mouse_data("middle", 1)
                mouse_click_positions["middle"].append(pos)
    elif isinstance(event, WheelEvent):
        delta_val = abs(event.delta)
        MouseStats.scroll_count += delta_val
        update_mouse_data("scroll", delta_val)
mouse.hook(handle_mouse_event)

def seconds_to_hms(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}h {m}m {s}s"
def update_activity():
    global last_activity_time
    last_activity_time = time.time()
app_running = True
def safe_after(delay, func):
    def wrapper():
        try:
            func()
        except Exception:
            pass
    try:
        root.after(delay, wrapper)
    except RuntimeError:
        pass
def get_ui_delay(delay):
    try:
        if root.winfo_viewable():
            return delay
    except Exception:
        return delay
    return delay * 10
def get_cached_font(url, filename):
    temp_dir = tempfile.gettempdir()
    font_path = os.path.join(temp_dir, filename)
    try:
        if os.path.exists(font_path):
            with open(font_path, "rb") as f:
                font_data = f.read()
            return font_path, font_data
    except Exception as e:
        print(f"error reading cached font {filename}: {e}")
    def download_font():
        nonlocal font_path
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            font_data = response.content
            with open(font_path, "wb") as f:
                f.write(font_data)
            if os.name == "nt":
                FR_PRIVATE = 0x10
                res = ctypes.windll.gdi32.AddFontResourceExW(font_path, FR_PRIVATE, 0)
                if res == 0:
                    print(f"failed to load font resource for {filename}")
        except Exception as e:
            print(f"error fetching font {filename}: {e}")
    threading.Thread(target=download_font, daemon=True).start()
    return font_path, None
POPPINS_FONT_URL = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf"
poppins_path, poppins_data = get_cached_font(POPPINS_FONT_URL, "Poppins-Bold.ttf")
if os.name == "nt" and poppins_path and os.path.exists(poppins_path):
    FR_PRIVATE = 0x10
    res = ctypes.windll.gdi32.AddFontResourceExW(poppins_path, FR_PRIVATE, 0)
    if res == 0:
        print("failed to load Poppins Bold font")
CUSTOM_FONT = ("Poppins", 16, "bold")
FA_FONT_URL = "https://github.com/FortAwesome/Font-Awesome/raw/6.4.0/webfonts/fa-solid-900.ttf"
fa_path, fa_data = get_cached_font(FA_FONT_URL, "fa-solid-900.ttf")
if os.name == "nt" and fa_path and os.path.exists(fa_path):
    res = ctypes.windll.gdi32.AddFontResourceExW(fa_path, FR_PRIVATE, 0)
    if res == 0:
        print("failed to load Font Awesome font")
FA_FONT = ("Font Awesome 6 Free Solid", 24)
_dummy_root = tk.Tk()
_dummy_root.withdraw()
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")
root = ctk.CTk()
root.title("Optimized Keyboard UI with Real-Time Updates")
root.configure(bg="#121212")
root.state("zoomed")
root.minsize(800, 600)
root.protocol("WM_DELETE_WINDOW", lambda: root.withdraw())

key_usage = {}
key_press_duration = {}
currently_pressed = {}
key_press_timestamps = []
total_key_count = 0
keyboard_keys = defaultdict(list)
app_start_time = time.time()
current_word = ""
word_usage = defaultdict(int)
word_daily_count = {}
last_activity_time = time.time()
all_curse_words_set = {"fuck", "fucker", "fucking", "fucked", "fuckface", "fuckhead", "fuckwit", "motherfucker", "motherfucking", "f u c k", "f.u.c.k", "f*ck", "f**k", "shit", "shitty", "shitter", "shithole", "bullshit", "crap", "damn", "dammit", "goddamn", "goddammit", "s hit", "s.h.i.t", "s#it", "bitch", "bitches", "bitching", "bastard", "bastards", "asshole", "assholes", "ass", "arse", "arsehole", "b i t c h", "b*tch", "b!tch", "dick", "dickhead", "dumbass", "dickweed", "dickwad", "d i c k", "cunt", "cunts", "cock", "cocks", "clit", "clits", "cum", "cummer", "cumming", "pussy", "pussies", "c u n t", "c*nt", "c!nt", "whore", "whores", "slut", "sluts"}
racial_slurs_set = {"adolf", "hitler", "jew", "nigger", "niggers", "fag", "faggot", "faggots", "kike", "kikes", "chink", "chinks", "spic", "spics", "wetback", "wetbacks", "gook", "gooks", "kkk", "k.k.k"}
curse_general_set = all_curse_words_set - racial_slurs_set
curse_general_count = 0
racial_slurs_count = 0
fastest_wpm = 0
screen_time_data = {}
app_usage = {}
app_streaks = {}
apps_used_today = set()
apps_used_yesterday = set()
last_streak_date = time.strftime("%Y-%m-%d")
emoji_usage = {}
def is_emoji(s):
    for ch in s:
        code = ord(ch)
        if (0x1F300 <= code <= 0x1F5FF) or (0x1F600 <= code <= 0x1F64F) or (0x1F680 <= code <= 0x1F6FF) or (0x1F700 <= code <= 0x1F77F) or (0x1F780 <= code <= 0x1F7FF) or (0x1F800 <= code <= 0x1F8FF) or (0x1F900 <= code <= 0x1F9FF) or (0x1FA00 <= code <= 0x1FA6F) or (0x1FA70 <= code <= 0x1FAFF):
            return True
    return False
def get_install_date():
    install_file = os.path.join(DATA_DIR, "install_date.txt")
    if os.path.exists(install_file):
        with open(install_file, "r") as f:
            date_str = f.read().strip()
        try:
            return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            pass
    today = datetime.date.today()
    with open(install_file, "w") as f:
        f.write(today.strftime("%Y-%m-%d"))
    return today
install_date = get_install_date()
def ordinal(n):
    if 11 <= (n % 100) <= 13:
        suffix = 'th'
    else:
        suffix = {1:'st',2:'nd',3:'rd'}.get(n % 10, 'th')
    return str(n) + suffix
def format_install_date(d):
    return d.strftime("%B ") + ordinal(d.day) + d.strftime(", %Y")
def compute_longest_session():
    if not key_press_timestamps:
        return 0
    sorted_times = sorted(key_press_timestamps)
    longest = current = 0
    session_start = sorted_times[0]
    prev = sorted_times[0]
    for t in sorted_times[1:]:
        if t - prev <= 300:
            current = t - session_start
        else:
            longest = max(longest, current)
            session_start = t
            current = 0
        prev = t
    longest = max(longest, current)
    return longest

content_frame = ctk.CTkFrame(root, fg_color="#121212", corner_radius=10)
content_frame.pack(expand=True, fill="both", padx=10, pady=10)
keyboard_frame = ctk.CTkFrame(content_frame, fg_color="#121212", corner_radius=10)
statistics_frame = ctk.CTkFrame(content_frame, fg_color="#121212", corner_radius=10)
recap_frame = ctk.CTkFrame(content_frame, fg_color="#121212", corner_radius=10)
screen_time_frame = ctk.CTkFrame(content_frame, fg_color="#121212", corner_radius=10)
mouse_frame = ctk.CTkFrame(content_frame, fg_color="#121212", corner_radius=10)
words_frame = ctk.CTkFrame(content_frame, fg_color="#121212", corner_radius=10)
export_frame = ctk.CTkFrame(content_frame, fg_color="#121212", corner_radius=10)
streaks_frame = ctk.CTkFrame(content_frame, fg_color="#121212", corner_radius=10)
lifetime_frame = ctk.CTkFrame(content_frame, fg_color="#121212", corner_radius=10)
current_screen = "Keyboard"
performance_mode_active = False
performance_mode_frame = None
UI_UPDATE_INTERVAL = 1000
SLOW_HARDWARE = True
KEY_COUNTS_INTERVAL = UI_UPDATE_INTERVAL
STATS_INTERVAL = UI_UPDATE_INTERVAL
CAPSLOCK_INTERVAL = UI_UPDATE_INTERVAL
maximized_fix_done = False
def check_window_state():
    global maximized_fix_done
    if not maximized_fix_done:
        if root.state() != "zoomed":
            root.state("zoomed")
            maximized_fix_done = True
    safe_after(500, check_window_state)
check_window_state()
def on_closing():
    root.withdraw()
def quit_app(icon, event):
    global app_running
    app_running = False
    icon.stop()
    os._exit(0)
def normalize_key(key):
    if key is None:
        return None
    key = key.strip()
    kl = key.lower()
    mapping = {"escape": "ESC", "esc": "ESC", "backspace": "Backspace", "return": "Enter", "enter": "Enter", "caps_lock": "Caps", "caps lock": "Caps", "capslock": "Caps", "shift": "Shift", "shift_l": "Left Shift", "left shift": "Left Shift", "shift_r": "Right Shift", "right shift": "Right Shift", "control": "CTRL", "ctrl": "CTRL", "control_l": "Left Ctrl", "control_r": "Right Ctrl", "alt": "Alt", "alt_l": "Left Alt", "alt_r": "Right Alt", "space": "SPACE", "tab": "Tab", "insert": "INSERT", "home": "HOME", "end": "END", "delete": "Delete", "print_screen": "PrtSc", "print screen": "PrtSc", "prtsc": "PrtSc", "prt sc": "PrtSc", "prtscr": "PrtSc", "fn": "Fn", "windows": "Win", "win": "Win", "super": "Win", "super_l": "Win", "super_r": "Win", "up": "↑", "down": "↓", "left": "←", "right": "→"}
    if kl in mapping:
        return mapping[kl]
    if kl.startswith("f") and kl[1:].isdigit():
        return kl.upper()
    if len(key) == 1 and key.isalpha():
        return key.upper()
    return key
sim_key_mapping = {"ESC": "esc", "Backspace": "backspace", "Enter": "enter", "Caps": "caps lock", "Shift": "shift", "Left Shift": "left shift", "Right Shift": "right shift", "CTRL": "ctrl", "Left Ctrl": "left ctrl", "Right Ctrl": "right ctrl", "Alt": "alt", "Left Alt": "left alt", "Right Alt": "right alt", "SPACE": "space", "Tab": "tab", "INSERT": "insert", "HOME": "home", "END": "end", "Delete": "delete", "PrtSc": "print screen", "Fn": "fn", "Win": "win", "↑": "up", "↓": "down", "←": "left", "→": "right"}
def get_sim_key(key):
    return sim_key_mapping.get(key, key.lower() if len(key) == 1 else key.lower())
class AestheticKey(ctk.CTkFrame):
    def __init__(self, master, text, width=60, height=60, norm_key=None, shadow_offset=4, **kwargs):
        super().__init__(master, width=width+shadow_offset, height=height+shadow_offset+20, fg_color="#121212", corner_radius=10, **kwargs)
        self.width = width
        self.height = height
        self.shadow_offset = shadow_offset
        self.display_text = text
        self.norm_key = norm_key if norm_key is not None else normalize_key(text)
        self.shadow = ctk.CTkFrame(self, width=width, height=height, fg_color="#1a1a1a", corner_radius=8)
        self.shadow.place(x=shadow_offset, y=shadow_offset)
        self.label = ctk.CTkLabel(self, text=text, width=width, height=height, fg_color="#2a2a2a", text_color="#FFFFFF", corner_radius=8, font=CUSTOM_FONT, anchor="center")
        self.label.place(x=0, y=0)
        self.count_label = ctk.CTkLabel(self, text="", font=("Poppins", 12, "bold"), text_color="#FFFFFF", fg_color="transparent")
        self.count_label.place(x=0, y=height+shadow_offset)
        self.previous_count = 0
        if self.norm_key in ["Caps", "CAPSLOCK"]:
            self.indicator_canvas = tk.Canvas(self, width=12, height=12, bg="#121212", highlightthickness=0)
            self.indicator_canvas.place(relx=1.0, y=5, anchor="ne", x=-5)
            self._current_indicator_color = "#808080"
            self.indicator = self.indicator_canvas.create_oval(0, 0, 12, 12, fill=self._current_indicator_color, outline="")
        self.bind("<ButtonPress-1>", self.press_handler)
        self.label.bind("<ButtonPress-1>", self.press_handler)
        self.bind("<ButtonRelease-1>", self.release_handler)
        self.label.bind("<ButtonRelease-1>", self.release_handler)
        self.pressed = False
        self.current_offset = 0
    def _hex_to_rgb(self, color):
        if not color.startswith("#"):
            r, g, b = root.winfo_rgb(color)
            color = "#%02x%02x%02x" % (r//256, g//256, b//256)
        color = color.lstrip("#")
        return tuple(int(color[i:i+2], 16) for i in (0, 2, 4))
    def _rgb_to_hex(self, rgb):
        return "#%02x%02x%02x" % rgb
    def _animate_indicator_color(self, start_color, end_color, steps=10, delay=30):
        start_rgb = self._hex_to_rgb(start_color)
        end_rgb = self._hex_to_rgb(end_color)
        def step(i):
            if i > steps:
                self._current_indicator_color = end_color
                self.indicator_canvas.itemconfig(self.indicator, fill=end_color)
                return
            new_rgb = tuple(int(start_rgb[j] + (end_rgb[j]-start_rgb[j]) * i/steps) for j in range(3))
            new_hex = self._rgb_to_hex(new_rgb)
            self.indicator_canvas.itemconfig(self.indicator, fill=new_hex)
            safe_after(delay, lambda: step(i+1))
        step(0)
    def animate_to(self, target_offset, steps=15, delay=5):
        start_offset = self.current_offset
        delta = (target_offset - start_offset) / steps
        def step(count):
            new_offset = start_offset + delta * count
            self.label.place_configure(x=new_offset, y=new_offset)
            if count < steps:
                safe_after(delay, lambda: step(count+1))
            else:
                self.current_offset = target_offset
        step(1)
    def on_press(self, event):
        if not self.pressed:
            self.pressed = True
            self.animate_to(self.shadow_offset)
    def on_release(self, event):
        if self.pressed:
            self.animate_to(0)
            self.pressed = False
    def animate_count_increase(self):
        big_font = ("Poppins", 16, "bold")
        base_font = ("Poppins", 12, "bold")
        self.count_label.configure(font=big_font)
        safe_after(0, lambda: self.count_label.configure(font=base_font))
    def update_count(self, count):
        self.count_label.configure(text=str(count))
        if count > self.previous_count:
            self.animate_count_increase()
        self.previous_count = count
    def set_capslock_state(self, active):
        target = "#66cc66" if active else "#808080"
        if target != self._current_indicator_color:
            self._animate_indicator_color(self._current_indicator_color, target)
    def press_handler(self, event):
        on_key_press(type("DummyEvent", (), {"keysym": self.norm_key, "from_ui": True, "char": self.norm_key}))
        if self.norm_key != "Fn":
            try:
                keyboard.press(get_sim_key(self.norm_key))
            except Exception as e:
                print(f"error pressing {self.norm_key}: {e}")
        self.on_press(event)
    def release_handler(self, event):
        if self.norm_key != "Fn":
            try:
                keyboard.release(get_sim_key(self.norm_key))
            except Exception as e:
                print(f"error releasing {self.norm_key}: {e}")
        on_key_release(type("DummyEvent", (), {"keysym": self.norm_key, "from_ui": True, "char": self.norm_key}))
        self.on_release(event)
def create_key(parent, key_label, width, height, norm_override=None):
    widget = AestheticKey(parent, text=key_label, width=width, height=height, norm_key=norm_override)
    if widget.norm_key is not None:
        keyboard_keys[widget.norm_key].append(widget)
    return widget
main_keys_frame = ctk.CTkFrame(keyboard_frame, fg_color="#121212", corner_radius=10)
main_keys_frame.pack(pady=10)
row_defs = [
    [("ESC", 60, 30), ("F1", 60, 30), ("F2", 60, 30), ("F3", 60, 30), ("F4", 60, 30), ("F5", 60, 30), ("F6", 60, 30), ("F7", 60, 30), ("F8", 60, 30), ("F9", 60, 30), ("F10", 60, 30), ("F11", 60, 30), ("F12", 60, 30), ("Home", 60, 30), ("End", 60, 30), ("Insert", 60, 30), ("Delete", 60, 30)],
    [("`", 60, 60), ("1", 60, 60), ("2", 60, 60), ("3", 60, 60), ("4", 60, 60), ("5", 60, 60), ("6", 60, 60), ("7", 60, 60), ("8", 60, 60), ("9", 60, 60), ("0", 60, 60), ("-", 60, 60), ("=", 60, 60), ("Delete", 100, 60, "Backspace")],
    [("Tab", 80, 60), ("Q", 60, 60), ("W", 60, 60), ("E", 60, 60), ("R", 60, 60), ("T", 60, 60), ("Y", 60, 60), ("U", 60, 60), ("I", 60, 60), ("O", 60, 60), ("P", 60, 60), ("[", 60, 60), ("]", 60, 60), ("\\", 60, 60)],
    [("Caps", 80, 60), ("A", 60, 60), ("S", 60, 60), ("D", 60, 60), ("F", 60, 60), ("G", 60, 60), ("H", 60, 60), ("J", 60, 60), ("K", 60, 60), ("L", 60, 60), (";", 60, 60), ("'", 60, 60), ("Enter", 100, 60)],
    [("Shift", 100, 60, "Left Shift"), ("Z", 60, 60), ("X", 60, 60), ("C", 60, 60), ("V", 60, 60), ("B", 60, 60), ("N", 60, 60), ("M", 60, 60), (",", 60, 60), (".", 60, 60), ("/", 60, 60), ("Shift", 100, 60, "Right Shift")]
]
for row in row_defs:
    row_frame = ctk.CTkFrame(main_keys_frame, fg_color="#121212", corner_radius=10)
    row_frame.pack(pady=5)
    for item in row:
        if len(item) == 4:
            key_label, key_w, key_h, norm_override = item
            widget = create_key(row_frame, key_label, key_w, key_h, norm_override)
        else:
            key_label, key_w, key_h = item
            widget = create_key(row_frame, key_label, key_w, key_h)
        widget.pack(side="left", padx=4)
space_row_frame = ctk.CTkFrame(keyboard_frame, fg_color="#121212", corner_radius=10)
space_row_frame.pack(pady=10)
space_keys = [("Fn", 60, 60), ("Ctrl", 60, 60, "Left Ctrl"), ("Win", 60, 60), ("Alt", 60, 60, "Left Alt"), ("Space", 300, 60), ("Alt", 60, 60, "Right Alt"), ("PrtSc", 60, 60), ("Ctrl", 60, 60, "Right Ctrl")]
for key_tuple in space_keys:
    if len(key_tuple) == 4:
        key_label, key_w, key_h, norm_override = key_tuple
        widget = create_key(space_row_frame, key_label, key_w, key_h, norm_override)
    else:
        key_label, key_w, key_h = key_tuple
        widget = create_key(space_row_frame, key_label, key_w, key_h)
    widget.grid(row=0, column=space_keys.index(key_tuple), padx=4, pady=4)
arrow_cluster_frame = ctk.CTkFrame(space_row_frame, width=60, height=60, fg_color="#121212", corner_radius=10)
arrow_cluster_frame.grid(row=0, column=len(space_keys), padx=4, pady=4)
up_key = create_key(arrow_cluster_frame, "↑", 30, 30)
up_key.place(x=15, y=0)
left_key = create_key(arrow_cluster_frame, "←", 30, 30)
left_key.place(x=0, y=30)
down_key = create_key(arrow_cluster_frame, "↓", 30, 30)
down_key.place(x=15, y=30)
right_key = create_key(arrow_cluster_frame, "→", 30, 30)
right_key.place(x=30, y=30)
performance_mode_var = ctk.BooleanVar(value=False)
def performance_mode_toggle():
    global performance_mode_active, performance_mode_frame
    if performance_mode_var.get():
        performance_mode_active = True
        for frm in [keyboard_frame, statistics_frame, export_frame, recap_frame, screen_time_frame, mouse_frame, words_frame, streaks_frame, lifetime_frame]:
            frm.pack_forget()
        if performance_mode_frame is None:
            performance_mode_frame = ctk.CTkFrame(content_frame, fg_color="#121212", corner_radius=10)
            performance_mode_frame.pack(expand=True, fill="both")
            title_label = ctk.CTkLabel(performance_mode_frame, text="Keyboard Logger", font=("Poppins", 32, "bold"), text_color="white", fg_color="transparent")
            title_label.pack(pady=(100,10))
            desc_label = ctk.CTkLabel(performance_mode_frame, text="Keyboard Logger is still tracking data in the background.\nOpen the app to view detailed stats.", font=("Poppins", 18), text_color="white", fg_color="transparent")
            desc_label.pack(pady=(0,20))
            open_button = ctk.CTkButton(performance_mode_frame, text="Open", font=("Poppins", 20), corner_radius=10, fg_color="#1a1a1a", hover_color="#333333", command=performance_mode_disable)
            open_button.pack(pady=20)
        else:
            performance_mode_frame.pack(expand=True, fill="both")
    else:
        performance_mode_disable()
def performance_mode_disable():
    global performance_mode_active, performance_mode_frame
    performance_mode_var.set(False)
    performance_mode_active = False
    if performance_mode_frame is not None:
        performance_mode_frame.pack_forget()
    if current_screen == "Keyboard":
        keyboard_frame.pack(expand=True, fill="both")
    elif current_screen == "Statistics":
        statistics_frame.pack(expand=True, fill="both")
    elif current_screen == "Export":
        export_frame.pack(expand=True, fill="both")
    elif current_screen == "Recap":
        recap_frame.pack(expand=True, fill="both")
    elif current_screen == "Screen Time":
        screen_time_frame.pack(expand=True, fill="both")
    elif current_screen == "Mouse":
        mouse_frame.pack(expand=True, fill="both")
    elif current_screen == "Words":
        words_frame.pack(expand=True, fill="both")
    elif current_screen == "Streaks":
        streaks_frame.pack(expand=True, fill="both")
    elif current_screen == "Lifetime":
        lifetime_frame.pack(expand=True, fill="both")
key_press_duration_mode = ctk.BooleanVar(value=False)
key_press_checkbox = ctk.CTkCheckBox(keyboard_frame, text="Key Presses", variable=key_press_duration_mode, font=("Poppins", 14), text_color="white", fg_color="#121212")
key_press_checkbox.place(relx=0.0, rely=1.0, anchor="sw", x=10, y=-10)
perf_checkbox = ctk.CTkCheckBox(keyboard_frame, text="Performance Mode", variable=performance_mode_var, font=("Poppins", 14), text_color="white", fg_color="#121212", command=performance_mode_toggle)
perf_checkbox.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)
stats_option_var = ctk.StringVar(value="Line Graph")
stats_option_menu = ctk.CTkOptionMenu(statistics_frame, values=["Line Graph", "Plain Text"], variable=stats_option_var, font=CUSTOM_FONT)
stats_option_menu.pack(pady=10)
stats_content_frame = ctk.CTkFrame(statistics_frame, fg_color="#121212", corner_radius=10)
stats_content_frame.pack(expand=True, fill="both", padx=10, pady=10)
graph_canvas = tk.Canvas(stats_content_frame, bg="#121212", highlightthickness=0)
graph_canvas.pack(expand=True, fill="both")
plain_text_box = ctk.CTkTextbox(stats_content_frame, font=("Poppins", 12, "bold"), fg_color="#121212", text_color="#FFFFFF")
plain_text_box.pack(expand=True, fill="both")
plain_text_box.configure(state="disabled")
plain_text_box.pack_forget()
def update_plain_text():
    plain_text_box.configure(state="normal")
    plain_text_box.delete("1.0", "end")
    for k in sorted(key_usage.keys()):
        if key_press_duration_mode.get():
            duration = key_press_duration.get(k, 0.0)
            plain_text_box.insert("end", f"{k}: {duration:.2f}s\n")
        else:
            plain_text_box.insert("end", f"{k}: {key_usage.get(k, 0)}\n")
    plain_text_box.configure(state="disabled")
def draw_line_graph():
    graph_canvas.delete("all")
    current_time = time.time()
    interval = 0.333
    display_time = current_time - interval
    window = 60
    t0 = max(app_start_time, display_time - window)
    num_points = int((display_time - t0) / interval)
    if num_points < 2:
        return
    data_points = []
    for i in range(num_points):
        t_start = t0 + i * interval
        t_end = t_start + interval
        count_in_interval = sum(1 for ts in key_press_timestamps if t_start <= ts < t_end)
        data_points.append((t_start, count_in_interval))
    times = [t for (t, _) in data_points]
    raw_rates = [r for (_, r) in data_points]
    if len(raw_rates) >= 3:
        smoothed_rates = [raw_rates[0]*0.5 + raw_rates[1]*0.5] + [0.25*raw_rates[i-1] + 0.5*raw_rates[i] + 0.25*raw_rates[i+1] for i in range(1, len(raw_rates)-1)] + [raw_rates[-2]*0.5 + raw_rates[-1]*0.5]
    else:
        smoothed_rates = raw_rates
    rate_min = min(smoothed_rates)
    rate_max = max(smoothed_rates) or (rate_min + 1)
    width = graph_canvas.winfo_width()
    height = graph_canvas.winfo_height()
    margin = 50
    def scale_x(t):
        return margin + (t - t0) / (display_time - t0) * (width - 2 * margin)
    def scale_y(r):
        return height - margin - (r - rate_min) / (rate_max - rate_min) * (height - 2 * margin)
    grid_color = "#2a2a2a"
    for i in range(5):
        y = margin + i * (height - 2 * margin) / 4
        graph_canvas.create_line(margin, y, width - margin, y, fill=grid_color)
        value = rate_max - i * (rate_max - rate_min) / 4
        graph_canvas.create_text(margin - 20, y, text=f"{value:.1f}", fill="white", font=("Poppins", 10))
    for i in range(6):
        x = margin + i * (width - 2 * margin) / 5
        graph_canvas.create_line(x, margin, x, height - margin, fill=grid_color)
    graph_canvas.create_line(margin, margin, margin, height - margin, fill="white", width=2)
    graph_canvas.create_line(margin, height - margin, width - margin, height - margin, fill="white", width=2)
    graph_canvas.create_text(width / 2, margin / 2, text="Key Press Rate (per interval)", fill="white", font=("Poppins", 14, "bold"))
    smoothed_points = [(scale_x(t), scale_y(r)) for t, r in zip(times, smoothed_rates)]
    coords = []
    for point in smoothed_points:
        coords.extend(point)
    graph_canvas.create_line(*coords, fill="cyan", width=2, smooth=True)
def update_statistics_display():
    option = stats_option_var.get()
    if option == "Line Graph":
        plain_text_box.pack_forget()
        graph_canvas.pack(expand=True, fill="both")
        draw_line_graph()
    elif option == "Plain Text":
        graph_canvas.pack_forget()
        plain_text_box.pack(expand=True, fill="both")
        update_plain_text()
    safe_after(get_ui_delay(STATS_INTERVAL), update_statistics_display)
update_statistics_display()
def update_key_counts():
    show_duration = key_press_duration_mode.get()
    for key, widget_list in keyboard_keys.items():
        if show_duration:
            duration = key_press_duration.get(key, 0.0)
            display = f"{duration:.2f}s"
        else:
            count = key_usage.get(key, 0)
            display = str(count)
        for widget in widget_list:
            widget.count_label.configure(text=display)
    safe_after(get_ui_delay(KEY_COUNTS_INTERVAL), update_key_counts)
update_key_counts()
def update_screen_time_loop():
    now = time.time()
    delta = now - update_screen_time_loop.last_check
    update_screen_time_loop.last_check = now
    today = time.strftime("%Y-%m-%d")
    if today not in screen_time_data:
        screen_time_data[today] = {"active": 0, "afk": 0}
    timeout = 300
    if now - last_activity_time < timeout:
        screen_time_data[today]["active"] += delta
        if os.name == "nt":
            try:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                buffer = ctypes.create_unicode_buffer(512)
                ctypes.windll.user32.GetWindowTextW(hwnd, buffer, 512)
                app_title = buffer.value
            except Exception:
                app_title = "Unknown"
        else:
            app_title = "Unknown"
        if app_title:
            app_usage[app_title] = app_usage.get(app_title, 0) + delta
            apps_used_today.add(app_title)
        refresh_rate = 1000
    else:
        screen_time_data[today]["afk"] += delta
        refresh_rate = 10000
    safe_after(refresh_rate, update_screen_time_loop)
update_screen_time_loop.last_check = time.time()
update_screen_time_loop()
lbl_active = None
lbl_app = None
lbl_avg = None
screen_time_title = ctk.CTkLabel(screen_time_frame, text="⏰ Screen Time", font=("Poppins", 28, "bold"), text_color="#FFFFFF", fg_color="#121212")
screen_time_title.pack(pady=(20, 10))
cards_container = ctk.CTkFrame(screen_time_frame, fg_color="#1a1a1a", corner_radius=10)
cards_container.pack(pady=10, padx=20, fill="both", expand=True)
def create_stat_card(parent, icon, title, value="Calculating..."):
    card = ctk.CTkFrame(parent, fg_color="#1a1a1a", corner_radius=15, height=100)
    card.pack(pady=10, padx=10, fill="x")
    card.grid_propagate(False)
    icon_label = ctk.CTkLabel(card, text=icon, font=("Poppins", 36), text_color="#FFD700", fg_color="#1a1a1a")
    icon_label.grid(row=0, column=0, rowspan=2, padx=20, pady=10)
    title_label = ctk.CTkLabel(card, text=title, font=("Poppins", 18, "bold"), text_color="white", fg_color="#1a1a1a")
    title_label.grid(row=0, column=1, sticky="w", pady=(20,0))
    value_label = ctk.CTkLabel(card, text=value, font=("Poppins", 16), text_color="white", fg_color="#1a1a1a")
    value_label.grid(row=1, column=1, sticky="w", pady=(0,20))
    card.columnconfigure(1, weight=1)
    return card, value_label
active_card, lbl_active = create_stat_card(cards_container, "⏱", "Today's Active Time")
app_card, lbl_app = create_stat_card(cards_container, "💻", "Most Used App Today")
avg_card, lbl_avg = create_stat_card(cards_container, "📊", "Average Active Time (Past 7 Days)")
def update_screen_time_ui():
    today = time.strftime("%Y-%m-%d")
    data = screen_time_data.get(today, {"active": 0, "afk": 0})
    active_time = data.get("active", 0)
    lbl_active.configure(text=seconds_to_hms(active_time))
    if app_usage:
        most_used = max(app_usage, key=lambda k: app_usage[k])
        lbl_app.configure(text=f"{most_used} ({seconds_to_hms(app_usage[most_used])})")
    else:
        lbl_app.configure(text="N/A")
    total = 0
    count = 0
    for i in range(7):
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
        if d in screen_time_data:
            total += screen_time_data[d].get("active", 0)
            count += 1
    avg = total / count if count else 0
    lbl_avg.configure(text=seconds_to_hms(avg))
    safe_after(get_ui_delay(1000), update_screen_time_ui)
update_screen_time_ui()
weekly_graph_label = ctk.CTkLabel(screen_time_frame, text="Weekly Screen Time", font=("Poppins", 24, "bold"), text_color="#FFFFFF", fg_color="#121212")
weekly_graph_label.pack(pady=(20,10))
weekly_graph_frame = ctk.CTkFrame(screen_time_frame, fg_color="#121212", corner_radius=10)
weekly_graph_frame.pack(pady=10, padx=20, fill="both")
h_scroll = ctk.CTkScrollbar(weekly_graph_frame, orientation="horizontal")
h_scroll.pack(side="bottom", fill="x")
weekly_canvas = tk.Canvas(weekly_graph_frame, bg="#121212", height=250, highlightthickness=0)
weekly_canvas.pack(side="top", fill="both", expand=True)
weekly_canvas.configure(xscrollcommand=h_scroll.set)
def update_weekly_bars():
    weekly_canvas.delete("all")
    today_date = datetime.date.today()
    days = [today_date - datetime.timedelta(days=i) for i in range(6, -1, -1)]
    day_data = []
    for day in days:
        day_str = day.strftime("%Y-%m-%d")
        active_seconds = screen_time_data.get(day_str, {}).get("active", 0)
        day_data.append((day, active_seconds))
    max_active = max([seconds for (_, seconds) in day_data] + [1])
    bar_width = 50
    gap = 20
    margin = 40
    max_bar_height = 150
    total_width = margin * 2 + (bar_width + gap) * len(day_data) - gap
    weekly_canvas.configure(scrollregion=(0, 0, total_width, 250))
    for idx, (day, active) in enumerate(day_data):
        x0 = margin + idx * (bar_width + gap)
        bar_height = int((active / max_active) * max_bar_height)
        y0 = 200 - bar_height
        y1 = 200
        weekly_canvas.create_rectangle(x0, y0, x0 + bar_width, y1, fill="#4CAF50", outline="")
        weekday_full = day.strftime("%A")
        weekly_canvas.create_text(x0 + bar_width / 2, 210, text=weekday_full, fill="white", font=("Poppins", 10))
        time_label = seconds_to_hms(active)
        weekly_canvas.create_text(x0 + bar_width / 2, y0 - 10, text=time_label, fill="white", font=("Poppins", 10))
    safe_after(get_ui_delay(1000), update_weekly_bars)
update_weekly_bars()
mouse_title = ctk.CTkLabel(mouse_frame, text="🖱 Mouse", font=("Poppins", 28, "bold"), text_color="#FFFFFF", fg_color="#121212")
mouse_title.pack(pady=(20,10))
mouse_scroll_canvas = tk.Canvas(mouse_frame, bg="#121212", highlightthickness=0)
mouse_scroll_canvas.pack(side="left", fill="both", expand=True)
mouse_v_scrollbar = ctk.CTkScrollbar(mouse_frame, orientation="vertical", command=mouse_scroll_canvas.yview)
mouse_v_scrollbar.pack(side="right", fill="y")
mouse_scroll_canvas.configure(yscrollcommand=mouse_v_scrollbar.set)
mouse_cards_container = ctk.CTkFrame(mouse_scroll_canvas, fg_color="#121212", corner_radius=10)
mouse_scroll_canvas.create_window((0, 0), window=mouse_cards_container, anchor="nw")
def on_mouse_cards_configure(event):
    mouse_scroll_canvas.configure(scrollregion=mouse_scroll_canvas.bbox("all"))
mouse_cards_container.bind("<Configure>", on_mouse_cards_configure)
def _on_mousewheel(event):
    mouse_scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
mouse_scroll_canvas.bind_all("<MouseWheel>", _on_mousewheel)
left_card, lbl_left = create_stat_card(mouse_cards_container, "👈", "Left Clicks")
right_card, lbl_right = create_stat_card(mouse_cards_container, "👉", "Right Clicks")
middle_card, lbl_middle = create_stat_card(mouse_cards_container, "👆", "Middle Clicks")
scroll_card, lbl_scroll = create_stat_card(mouse_cards_container, "🌀", "Scrolls")
distance_card, lbl_distance = create_stat_card(mouse_cards_container, "📏", "Distance Moved")
def update_mouse_ui():
    lbl_left.configure(text=str(MouseStats.left_clicks))
    lbl_right.configure(text=str(MouseStats.right_clicks))
    lbl_middle.configure(text=str(MouseStats.middle_clicks))
    lbl_scroll.configure(text=str(int(MouseStats.scroll_count)))
    lbl_distance.configure(text=f"{int(MouseStats.total_distance)} px")
    safe_after(get_ui_delay(1000), update_mouse_ui)
update_mouse_ui()
mouse_graph_label = ctk.CTkLabel(mouse_frame, text="Weekly Clicks", font=("Poppins", 24, "bold"), text_color="#FFFFFF", fg_color="#121212")
mouse_graph_label.pack(pady=(20,10))
mouse_graph_frame = ctk.CTkFrame(mouse_frame, fg_color="#121212", corner_radius=10)
mouse_graph_frame.pack(pady=10, padx=20, fill="both")
mouse_h_scroll = ctk.CTkScrollbar(mouse_graph_frame, orientation="horizontal", command=lambda *args: mouse_canvas.xview(*args))
mouse_h_scroll.pack(side="bottom", fill="x")
mouse_canvas = tk.Canvas(mouse_graph_frame, bg="#121212", height=250, highlightthickness=0)
mouse_canvas.pack(side="top", fill="both", expand=True)
mouse_canvas.configure(xscrollcommand=mouse_h_scroll.set)
def update_mouse_line_graph():
    mouse_canvas.delete("all")
    today_date = datetime.date.today()
    days = [today_date - datetime.timedelta(days=i) for i in range(6, -1, -1)]
    day_clicks = []
    for day in days:
        day_str = day.strftime("%Y-%m-%d")
        data = mouse_data.get(day_str, {"left": 0, "right": 0, "middle": 0})
        total_clicks = data.get("left", 0) + data.get("right", 0) + data.get("middle", 0)
        day_clicks.append((day, total_clicks))
    max_clicks = max([clicks for (_, clicks) in day_clicks] + [1])
    bar_width = 50
    gap = 20
    margin = 40
    max_graph_height = 150
    total_width = margin * 2 + (bar_width + gap) * len(day_clicks) - gap
    mouse_canvas.configure(scrollregion=(0, 0, total_width, 250))
    points = []
    for idx, (day, clicks) in enumerate(day_clicks):
        x = margin + idx * (bar_width + gap) + bar_width / 2
        y = 200 - (clicks / max_clicks) * max_graph_height
        points.append((x, y))
        day_label = day.strftime("%a")
        mouse_canvas.create_text(x, 210, text=day_label, fill="white", font=("Poppins", 12))
        mouse_canvas.create_text(x, y - 10, text=str(clicks), fill="white", font=("Poppins", 10))
    if len(points) >= 2:
        coords = []
        for p in points:
            coords.extend(p)
        mouse_canvas.create_line(*coords, fill="cyan", width=2, smooth=True)
    safe_after(get_ui_delay(1000), update_mouse_line_graph)
update_mouse_line_graph()
distance_graph_label = ctk.CTkLabel(mouse_frame, text="Weekly Total Distance Moved", font=("Poppins", 24, "bold"), text_color="#FFFFFF", fg_color="#121212")
distance_graph_label.pack(pady=(20,10))
distance_graph_frame = ctk.CTkFrame(mouse_frame, fg_color="#121212", corner_radius=10)
distance_graph_frame.pack(pady=10, padx=20, fill="both")
distance_h_scroll = ctk.CTkScrollbar(distance_graph_frame, orientation="horizontal")
distance_h_scroll.pack(side="bottom", fill="x")
distance_canvas = tk.Canvas(distance_graph_frame, bg="#121212", height=250, highlightthickness=0)
distance_canvas.pack(side="top", fill="both", expand=True)
distance_canvas.configure(xscrollcommand=distance_h_scroll.set)
def update_mouse_distance_graph():
    distance_canvas.delete("all")
    today_date = datetime.date.today()
    days = [today_date - datetime.timedelta(days=i) for i in range(6, -1, -1)]
    day_distances = []
    for day in days:
        day_str = day.strftime("%Y-%m-%d")
        distance = mouse_data.get(day_str, {}).get("distance", 0)
        day_distances.append((day, distance))
    max_distance = max([d for (_, d) in day_distances] + [1])
    bar_width = 50
    gap = 20
    margin = 40
    max_bar_height = 150
    total_width = margin * 2 + (bar_width + gap) * len(day_distances) - gap
    distance_canvas.configure(scrollregion=(0, 0, total_width, 250))
    for idx, (day, distance) in enumerate(day_distances):
        x0 = margin + idx * (bar_width + gap)
        bar_height = int((distance / max_distance) * max_bar_height)
        y0 = 200 - bar_height
        y1 = 200
        distance_canvas.create_rectangle(x0, y0, x0 + bar_width, y1, fill="#FFA07A", outline="")
        weekday_full = day.strftime("%A")
        distance_canvas.create_text(x0 + bar_width / 2, 210, text=weekday_full, fill="white", font=("Poppins", 10))
        distance_canvas.create_text(x0 + bar_width / 2, y0 - 10, text=f"{int(distance)} px", fill="white", font=("Poppins", 10))
    safe_after(get_ui_delay(1000), update_mouse_distance_graph)
update_mouse_distance_graph()
def download_heatmap_data():
    if pyautogui is None or Image is None:
        print("required libraries for heatmap (pyautogui and pillow) are not installed.")
        return
    screenshot = pyautogui.screenshot()
    screenshot = screenshot.convert("RGBA")
    width, height = screenshot.size
    overlay = Image.new("RGBA", (width, height), (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    all_clicks = mouse_click_positions["left"] + mouse_click_positions["right"] + mouse_click_positions["middle"]
    for (x, y) in all_clicks:
        radius = 20
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=(255,0,0,80))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=15))
    heatmap = Image.alpha_composite(screenshot, overlay)
    downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(downloads_dir, f"heatmap_{timestamp}.png")
    try:
        heatmap.save(filename)
        print(f"heatmap saved to {filename}")
    except Exception as e:
        print(f"error saving heatmap: {e}")
download_heatmap_button = ctk.CTkButton(mouse_frame, text="Download Heatmap", font=("Poppins", 16), command=download_heatmap_data)
download_heatmap_button.pack(pady=10)
words_title = ctk.CTkLabel(words_frame, text="✏️ Words", font=("Poppins", 28, "bold"), text_color="#FFFFFF", fg_color="#121212")
words_title.pack(pady=(20,10))
words_textbox = ctk.CTkTextbox(words_frame, font=("Poppins", 14, "bold"), fg_color="#121212", text_color="#FFFFFF", height=200)
words_textbox.pack(pady=10, padx=20, fill="x")
words_textbox.configure(state="disabled")
weekly_words_label = ctk.CTkLabel(words_frame, text="Weekly Word Count", font=("Poppins", 24, "bold"), text_color="#FFFFFF", fg_color="#121212")
weekly_words_label.pack(pady=(20,10))
weekly_words_frame = ctk.CTkFrame(words_frame, fg_color="#121212", corner_radius=10)
weekly_words_frame.pack(pady=10, padx=20, fill="both")
words_canvas = tk.Canvas(weekly_words_frame, bg="#121212", height=250, highlightthickness=0)
words_canvas.pack(side="top", fill="both", expand=True)
words_h_scroll = ctk.CTkScrollbar(weekly_words_frame, orientation="horizontal", command=words_canvas.xview)
words_h_scroll.pack(side="bottom", fill="x")
words_canvas.configure(xscrollcommand=words_h_scroll.set)
def update_words_ui():
    pos = words_textbox.yview()
    words_textbox.configure(state="normal")
    words_textbox.delete("1.0", "end")
    sorted_words = sorted(word_usage.items(), key=lambda kv: kv[1], reverse=True)[:75]
    for word, count in sorted_words:
        words_textbox.insert("end", f"{word}: {count}\n")
    words_textbox.configure(state="disabled")
    try:
        words_textbox.yview_moveto(pos[0])
    except Exception:
        pass
    today_date = datetime.date.today()
    last7days = [today_date - datetime.timedelta(days=i) for i in range(6, -1, -1)]
    day_labels = []
    day_counts = []
    for day in last7days:
        day_str = day.strftime("%Y-%m-%d")
        count = word_daily_count.get(day_str, 0)
        day_labels.append(day.strftime("%a"))
        day_counts.append(count)
    words_canvas.delete("all")
    max_count = max(day_counts + [1])
    bar_width = 50
    gap = 20
    margin = 40
    max_bar_height = 150
    total_width = margin * 2 + (bar_width + gap) * len(day_counts) - gap
    words_canvas.configure(scrollregion=(0, 0, total_width, 250))
    for idx, count in enumerate(day_counts):
        x0 = margin + idx * (bar_width + gap)
        bar_height = int((count / max_count) * max_bar_height)
        y0 = 200 - bar_height
        y1 = 200
        words_canvas.create_rectangle(x0, y0, x0 + bar_width, y1, fill="#FFA500", outline="")
        words_canvas.create_text(x0 + bar_width / 2, y1 + 15, text=day_labels[idx], fill="white", font=("Poppins", 12))
        words_canvas.create_text(x0 + bar_width / 2, y0 - 10, text=str(count), fill="white", font=("Poppins", 10))
    safe_after(get_ui_delay(1000), update_words_ui)
update_words_ui()
def switch_screen(screen):
    global current_screen
    current_screen = screen
    if performance_mode_active:
        return
    for frm in [keyboard_frame, statistics_frame, export_frame, recap_frame, screen_time_frame, mouse_frame, words_frame, streaks_frame, lifetime_frame]:
        frm.pack_forget()
    if screen == "Keyboard":
        keyboard_frame.pack(expand=True, fill="both")
    elif screen == "Statistics":
        statistics_frame.pack(expand=True, fill="both")
    elif screen == "Export":
        export_frame.pack(expand=True, fill="both")
    elif screen == "Recap":
        recap_frame.pack(expand=True, fill="both")
    elif screen == "Screen Time":
        screen_time_frame.pack(expand=True, fill="both")
    elif screen == "Mouse":
        mouse_frame.pack(expand=True, fill="both")
    elif screen == "Words":
        words_frame.pack(expand=True, fill="both")
    elif screen == "Streaks":
        streaks_frame.pack(expand=True, fill="both")
    elif screen == "Lifetime":
        lifetime_frame.pack(expand=True, fill="both")
sidebar_width = 300
sidebar_height = 500
sidebar_y = 10
sidebar_current_x = -sidebar_width
sidebar_panel = ctk.CTkFrame(root, fg_color="#2E3B4E", width=sidebar_width, height=sidebar_height, corner_radius=20)
sidebar_panel.place(x=sidebar_current_x, y=sidebar_y)
btn_font = ("Poppins", 18, "bold")
btn_params = {"font": btn_font, "fg_color": "#3E4A59", "hover_color": "#5A6775", "corner_radius": 10}
btn_keyboard = ctk.CTkButton(sidebar_panel, text="Keyboard", command=lambda: [switch_screen("Keyboard"), animate_sidebar_close()], **btn_params)
btn_keyboard.pack(pady=12, padx=20, fill="x")
btn_statistics = ctk.CTkButton(sidebar_panel, text="Statistics", command=lambda: [switch_screen("Statistics"), animate_sidebar_close()], **btn_params)
btn_statistics.pack(pady=12, padx=20, fill="x")
btn_export = ctk.CTkButton(sidebar_panel, text="Export", command=lambda: [switch_screen("Export"), animate_sidebar_close()], **btn_params)
btn_export.pack(pady=12, padx=20, fill="x")
btn_recap = ctk.CTkButton(sidebar_panel, text="Recap", command=lambda: [switch_screen("Recap"), animate_sidebar_close()], **btn_params)
btn_recap.pack(pady=12, padx=20, fill="x")
btn_screen_time = ctk.CTkButton(sidebar_panel, text="Screen Time", command=lambda: [switch_screen("Screen Time"), animate_sidebar_close()], **btn_params)
btn_screen_time.pack(pady=12, padx=20, fill="x")
btn_mouse = ctk.CTkButton(sidebar_panel, text="Mouse", command=lambda: [switch_screen("Mouse"), animate_sidebar_close()], **btn_params)
btn_mouse.pack(pady=12, padx=20, fill="x")
btn_words = ctk.CTkButton(sidebar_panel, text="Words", command=lambda: [switch_screen("Words"), animate_sidebar_close()], **btn_params)
btn_words.pack(pady=12, padx=20, fill="x")
btn_streaks = ctk.CTkButton(sidebar_panel, text="Streaks", command=lambda: [switch_screen("Streaks"), animate_sidebar_close()], **btn_params)
btn_streaks.pack(pady=12, padx=20, fill="x")
btn_lifetime = ctk.CTkButton(sidebar_panel, text="Lifetime", command=lambda: [switch_screen("Lifetime"), animate_sidebar_close()], **btn_params)
btn_lifetime.pack(pady=12, padx=20, fill="x")
def animate_sidebar_open():
    global sidebar_current_x
    target_x = 0
    step = 20
    if sidebar_current_x < target_x:
        sidebar_current_x = min(target_x, sidebar_current_x + step)
        sidebar_panel.place(x=sidebar_current_x, y=sidebar_y)
        safe_after(10, animate_sidebar_open)
    else:
        sidebar_panel.place(x=target_x, y=sidebar_y)
def animate_sidebar_close():
    global sidebar_current_x
    target_x = -sidebar_width
    step = 20
    if sidebar_current_x > target_x:
        sidebar_current_x = max(target_x, sidebar_current_x - step)
        sidebar_panel.place(x=sidebar_current_x, y=sidebar_y)
        safe_after(10, animate_sidebar_close)
    else:
        sidebar_panel.place(x=target_x, y=sidebar_y)
def open_sidebar():
    animate_sidebar_open()
def update_positions(event=None):
    if sidebar_panel.winfo_exists():
        sidebar_panel.place_configure(y=sidebar_y)
    hamburger_button.place_configure(x=10, y=10, anchor="nw")
root.bind("<Configure>", update_positions)
def hex_to_rgb(color):
    if not color.startswith("#"):
        r, g, b = root.winfo_rgb(color)
        color = "#%02x%02x%02x" % (r//256, g//256, b//256)
    color = color.lstrip("#")
    return tuple(int(color[i:i+2], 16) for i in (0, 2, 4))
def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % rgb
def animate_button_color(widget, start_color, end_color, steps=10, delay=30):
    start_rgb = hex_to_rgb(start_color)
    end_rgb = hex_to_rgb(end_color)
    def step(i):
        if i > steps:
            widget.configure(fg_color=end_color)
            return
        new_rgb = tuple(int(start_rgb[j] + (end_rgb[j]-start_rgb[j]) * i/steps) for j in range(3))
        widget.configure(fg_color=rgb_to_hex(new_rgb))
        widget.after(delay, lambda: step(i+1))
    step(0)
def animate_hamburger_hover_in(event):
    animate_button_color(hamburger_button, hamburger_button.cget("fg_color"), "#333333")
def animate_hamburger_hover_out(event):
    animate_button_color(hamburger_button, hamburger_button.cget("fg_color"), root.cget("bg"))
hamburger_button = ctk.CTkButton(root, text="\uf0c9", font=FA_FONT, width=40, height=40, fg_color=root.cget("bg"), hover_color=root.cget("bg"), corner_radius=20, command=open_sidebar, text_color="white")
hamburger_button.place(x=10, y=10, anchor="nw")
hamburger_button.bind("<Enter>", animate_hamburger_hover_in)
hamburger_button.bind("<Leave>", animate_hamburger_hover_out)
def on_ctrl_c(event):
    on_closing()
root.bind("<Control-c>", on_ctrl_c)
def release_all_keys():
    for key in list(currently_pressed.keys()):
        dummy = type("DummyEvent", (), {})()
        dummy.keysym = key
        dummy.from_hook = True
        on_key_release(dummy)
def on_focus_in(event):
    global focus_lost_time
    focus_lost_time = None
    performance_mode_var.set(False)
    performance_mode_disable()
def on_focus_out(event):
    global focus_lost_time
    focus_lost_time = time.time()
    def check_focus_loss():
        if focus_lost_time is not None and (time.time() - focus_lost_time) >= 60:
            performance_mode_var.set(True)
            performance_mode_toggle()
    safe_after(60000, check_focus_loss)
    release_all_keys()
root.bind("<FocusIn>", on_focus_in)
root.bind("<FocusOut>", on_focus_out)
key_event_queue = Queue()
def process_key_events():
    while not key_event_queue.empty():
        event_type, event_obj = key_event_queue.get()
        if event_type == "press":
            on_key_press(event_obj)
        elif event_type == "release":
            on_key_release(event_obj)
    safe_after(50, process_key_events)
process_key_events()
def on_key_press(event):
    global total_key_count, current_word, curse_general_count, racial_slurs_count
    if not getattr(event, "keysym", None):
        return
    update_activity()
    key = normalize_key(event.keysym)
    if hasattr(event, "char") and event.char and is_emoji(event.char):
        emoji_usage[event.char] = emoji_usage.get(event.char, 0) + 1
    if key in currently_pressed:
        return
    currently_pressed[key] = time.time()
    total_key_count += 1
    key_usage[key] = key_usage.get(key, 0) + 1
    key_press_timestamps.append(time.time())
    if key in keyboard_keys:
        for widget in keyboard_keys[key]:
            widget.on_press(event)
    if len(key) == 1 and key.isalpha():
        current_word += key.lower()
    if key in ["SPACE", "Enter"]:
        if current_word and len(current_word) >= 2:
            word_usage[current_word] += 1
            today = time.strftime("%Y-%m-%d")
            word_daily_count[today] = word_daily_count.get(today, 0) + 1
            lower_word = current_word.lower()
            if lower_word in racial_slurs_set:
                racial_slurs_count += 1
            elif lower_word in curse_general_set:
                curse_general_count += 1
        current_word = ""
    if key == "Tab":
        def check_alt_fallback():
            if not any(k in currently_pressed for k in ["Alt", "Left Alt", "Right Alt"]):
                key_usage["Alt"] = key_usage.get("Alt", 0) + 1
                for widget in keyboard_keys.get("Alt", []):
                    widget.update_count(key_usage["Alt"])
        safe_after(10000, check_alt_fallback)
    if key in ["Alt", "Left Alt", "Right Alt"]:
        def check_tab_fallback():
            if "Tab" not in currently_pressed:
                key_usage["Tab"] = key_usage.get("Tab", 0) + 1
                for widget in keyboard_keys.get("Tab", []):
                    widget.update_count(key_usage["Tab"])
        safe_after(10000, check_tab_fallback)
def on_key_release(event):
    if not getattr(event, "keysym", None):
        return
    key = normalize_key(event.keysym)
    if key in currently_pressed:
        press_time = currently_pressed.pop(key)
        duration = time.time() - press_time
        key_press_duration[key] = key_press_duration.get(key, 0.0) + duration
    if key in keyboard_keys:
        for widget in keyboard_keys[key]:
            widget.on_release(event)
def global_key_event(e):
    if not getattr(e, "name", None):
        return
    dummy_event = type("DummyEvent", (), {})()
    dummy_event.keysym = e.name
    dummy_event.from_hook = True
    if hasattr(e, "char"):
        dummy_event.char = e.char
    else:
        dummy_event.char = ""
    if e.event_type == "down":
        key_event_queue.put(("press", dummy_event))
    elif e.event_type == "up":
        key_event_queue.put(("release", dummy_event))
keyboard.hook(global_key_event)
keyboard.on_press_key("alt", lambda e: on_key_press(type("DummyEvent", (), {"keysym": "Alt", "from_hook": True, "char": "Alt"})))
keyboard.on_release_key("alt", lambda e: on_key_release(type("DummyEvent", (), {"keysym": "Alt", "from_hook": True, "char": "Alt"})))
special_keys = ["Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R", "Super_L", "Super_R", "Up", "Down", "Left", "Right", "Caps_Lock"]
for sk in special_keys:
    try:
        root.bind_all(f"<KeyPress-{sk}>", on_key_press)
        root.bind_all(f"<KeyRelease-{sk}>", on_key_release)
    except Exception as e:
        print(f"skipping binding for {sk}: {e}")
root.bind_all("<KeyRelease-Shift_R>", on_key_release)
def on_tab_press(event):
    on_key_press(event)
    return "break"
def on_tab_release(event):
    on_key_release(event)
    return "break"
root.bind_all("<KeyPress-Tab>", on_tab_press)
root.bind_all("<KeyRelease-Tab>", on_tab_release)
if os.name == "nt":
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    VK_LWIN = 0x5B
    VK_RWIN = 0x5C
    VK_F10 = 0x79
    try:
        LRESULT = ctypes.wintypes.LRESULT
    except AttributeError:
        LRESULT = ctypes.c_long
    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_ulong)]
    LowLevelKeyboardProc = ctypes.WINFUNCTYPE(LRESULT, wintypes.INT, wintypes.WPARAM, wintypes.LPARAM)
    def py_low_level_keyboard_proc(nCode, wParam, lParam):
        if nCode == 0:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            dummy = type("DummyEvent", (), {})()
            if kb.vkCode in (VK_LWIN, VK_RWIN, VK_F10):
                dummy.keysym = "F10" if kb.vkCode == VK_F10 else "Win"
                if wParam == WM_KEYDOWN:
                    on_key_press(dummy)
                elif wParam == WM_KEYUP:
                    on_key_release(dummy)
        return user32.CallNextHookEx(hook_id, nCode, wParam, lParam)
    LowLevelKeyboardProcPtr = LowLevelKeyboardProc(py_low_level_keyboard_proc)
    user32.SetWindowsHookExW.argtypes = [wintypes.INT, LowLevelKeyboardProc, wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    hook_id = user32.SetWindowsHookExW(WH_KEYBOARD_LL, LowLevelKeyboardProcPtr, kernel32.GetModuleHandleW(None), 0)
    def pump_messages():
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    threading.Thread(target=pump_messages, daemon=True).start()
def get_capslock_state():
    if os.name == "nt":
        return bool(ctypes.windll.user32.GetKeyState(0x14) & 1)
    return False
def update_capslock_indicator():
    state = get_capslock_state()
    for widget in keyboard_keys.get("Caps", []):
        widget.set_capslock_state(state)
    safe_after(get_ui_delay(CAPSLOCK_INTERVAL), update_capslock_indicator)
update_capslock_indicator()
recap_title = ctk.CTkLabel(recap_frame, text="Recap", font=("Poppins", 24, "bold"), text_color="white", fg_color="#121212")
recap_title.pack(pady=20)
card_frame2 = ctk.CTkFrame(recap_frame, fg_color="#1a1a1a", corner_radius=8)
card_frame2.pack(pady=10, padx=20, fill="x")
avg_wpm_label = ctk.CTkLabel(card_frame2, text="Average WPM: 0", font=CUSTOM_FONT, text_color="white", fg_color="transparent")
avg_wpm_label.pack(pady=10, padx=10)
card_frame3 = ctk.CTkFrame(recap_frame, fg_color="#1a1a1a", corner_radius=8)
card_frame3.pack(pady=10, padx=20, fill="x")
fastest_wpm_label = ctk.CTkLabel(card_frame3, text="Fastest WPM: 0", font=CUSTOM_FONT, text_color="white", fg_color="transparent")
fastest_wpm_label.pack(pady=10, padx=10)
card_frame4 = ctk.CTkFrame(recap_frame, fg_color="#1a1a1a", corner_radius=8)
card_frame4.pack(pady=10, padx=20, fill="x")
most_used_label = ctk.CTkLabel(card_frame4, text="Most Used Key: N/A", font=CUSTOM_FONT, text_color="white", fg_color="transparent")
most_used_label.pack(pady=10, padx=10)
card_frame5 = ctk.CTkFrame(recap_frame, fg_color="#1a1a1a", corner_radius=8)
card_frame5.pack(pady=10, padx=20, fill="x")
most_typed_word_label = ctk.CTkLabel(card_frame5, text="Most Typed Word: N/A", font=CUSTOM_FONT, text_color="white", fg_color="transparent")
most_typed_word_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
least_typed_word_label = ctk.CTkLabel(card_frame5, text="Least Typed Word: N/A", font=CUSTOM_FONT, text_color="white", fg_color="transparent")
least_typed_word_label.grid(row=1, column=0, padx=10, pady=5, sticky="w")
card_frame6 = ctk.CTkFrame(recap_frame, fg_color="#1a1a1a", corner_radius=8)
card_frame6.pack(pady=10, padx=20, fill="x")
most_used_char_label = ctk.CTkLabel(card_frame6, text="Most Used Character: N/A", font=CUSTOM_FONT, text_color="white", fg_color="transparent")
most_used_char_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
least_used_char_label = ctk.CTkLabel(card_frame6, text="Least Used Character: N/A", font=CUSTOM_FONT, text_color="white", fg_color="transparent")
least_used_char_label.grid(row=1, column=0, padx=10, pady=5, sticky="w")
card_frame7 = ctk.CTkFrame(recap_frame, fg_color="#1a1a1a", corner_radius=8)
card_frame7.pack(pady=10, padx=20, fill="x")
curse_general_label = ctk.CTkLabel(card_frame7, text="General Curse Words Typed: 0", font=CUSTOM_FONT, text_color="white", fg_color="transparent")
curse_general_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
racial_slurs_label = ctk.CTkLabel(card_frame7, text="Racial Slurs Typed: 0", font=CUSTOM_FONT, text_color="white", fg_color="transparent")
racial_slurs_label.grid(row=1, column=0, padx=10, pady=5, sticky="w")
def update_recap():
    global fastest_wpm
    elapsed_minutes = (time.time() - app_start_time) / 60
    avg_wpm = (total_key_count / 5) / elapsed_minutes if elapsed_minutes > 0 else 0
    now = time.time()
    keys_last_10 = sum(1 for ts in key_press_timestamps if now - ts <= 10)
    current_wpm = (keys_last_10 / 5) / (10/60)
    if current_wpm > fastest_wpm:
        fastest_wpm = current_wpm
    if key_usage:
        most_used = max(key_usage, key=lambda k: key_usage[k])
        most_used_text = f"{most_used} ({key_usage[most_used]})"
    else:
        most_used_text = "N/A"
    avg_wpm_label.configure(text=f"Average WPM: {avg_wpm:.1f}")
    fastest_wpm_label.configure(text=f"Fastest WPM: {fastest_wpm:.1f}")
    most_used_label.configure(text=f"Most Used Key: {most_used_text}")
    valid_words = {w: cnt for w, cnt in word_usage.items() if cnt >=20 and w.isalpha() and len(w) >= 3}
    if valid_words:
        most_typed_word = max(valid_words, key=lambda k: valid_words[k])
        least_typed_word = min(valid_words, key=lambda k: valid_words[k])
    else:
        most_typed_word = "N/A"
        least_typed_word = "N/A"
    most_typed_word_label.configure(text=f"Most Typed Word: {most_typed_word} ({word_usage.get(most_typed_word,0)})")
    least_typed_word_label.configure(text=f"Least Typed Word: {least_typed_word} ({word_usage.get(least_typed_word,0)})")
    char_usage = {ch: cnt for ch, cnt in key_usage.items() if len(ch) == 1 and ch.isprintable()}
    if char_usage:
        most_used_char = max(char_usage, key=lambda k: char_usage[k])
        least_used_char = min(char_usage, key=lambda k: char_usage[k])
    else:
        most_used_char = "N/A"
        least_used_char = "N/A"
    most_used_char_label.configure(text=f"Most Used Character: {most_used_char} ({char_usage.get(most_used_char,0)})")
    least_used_char_label.configure(text=f"Least Used Character: {least_used_char} ({char_usage.get(least_used_char,0)})")
    curse_general_label.configure(text=f"General Curse Words Typed: {curse_general_count}")
    racial_slurs_label.configure(text=f"Racial Slurs Typed: {racial_slurs_count}")
    safe_after(get_ui_delay(1000), update_recap)
update_recap()
lifetime_title = ctk.CTkLabel(lifetime_frame, text="Lifetime Stats", font=("Poppins", 28, "bold"), text_color="white", fg_color="#121212")
lifetime_title.pack(pady=20)
lifetime_stats_container = ctk.CTkFrame(lifetime_frame, fg_color="#1a1a1a", corner_radius=10)
lifetime_stats_container.pack(pady=10, padx=20, fill="both", expand=True)
lifetime_hours_label = ctk.CTkLabel(lifetime_stats_container, text="Total Hours Spent: Calculating...", font=("Poppins", 16), text_color="white", fg_color="transparent")
lifetime_hours_label.pack(pady=5, padx=10, anchor="w")
lifetime_days_label = ctk.CTkLabel(lifetime_stats_container, text="Total Days Spent: Calculating...", font=("Poppins", 16), text_color="white", fg_color="transparent")
lifetime_days_label.pack(pady=5, padx=10, anchor="w")
lifetime_key_press_label = ctk.CTkLabel(lifetime_stats_container, text="Total Key Press Time: Calculating...", font=("Poppins", 16), text_color="white", fg_color="transparent")
lifetime_key_press_label.pack(pady=5, padx=10, anchor="w")
lifetime_words_label = ctk.CTkLabel(lifetime_stats_container, text="Total Words Typed: Calculating...", font=("Poppins", 16), text_color="white", fg_color="transparent")
lifetime_words_label.pack(pady=5, padx=10, anchor="w")
lifetime_session_label = ctk.CTkLabel(lifetime_stats_container, text="Longest Session: Calculating...", font=("Poppins", 16), text_color="white", fg_color="transparent")
lifetime_session_label.pack(pady=5, padx=10, anchor="w")
lifetime_install_label = ctk.CTkLabel(lifetime_stats_container, text=f"Installed On: {format_install_date(install_date)}", font=("Poppins", 16), text_color="white", fg_color="transparent")
lifetime_install_label.pack(pady=5, padx=10, anchor="w")
def update_lifetime_stats():
    total_active = sum(day_data.get("active", 0) for day_data in screen_time_data.values())
    hours = total_active / 3600
    lifetime_hours_label.configure(text=f"Total Hours Spent: {hours:.1f} hours")
    days = hours / 24
    lifetime_days_label.configure(text=f"Total Days Spent: {days:.1f} days")
    total_key_press_seconds = sum(key_press_duration.values())
    total_key_press_minutes = total_key_press_seconds / 60
    lifetime_key_press_label.configure(text=f"Total Key Press Time: {total_key_press_minutes:.1f} minutes")
    total_words = sum(word_usage.values())
    lifetime_words_label.configure(text=f"Total Words Typed: {total_words}")
    longest_session = compute_longest_session()
    lifetime_session_label.configure(text=f"Longest Session: {seconds_to_hms(longest_session)}")
    safe_after(get_ui_delay(1000), update_lifetime_stats)
update_lifetime_stats()
def save_data():
    keyboard_data = {
        "timestamp": time.time(),
        "key_usage": key_usage,
        "total_key_count": total_key_count,
        "key_press_duration": key_press_duration
    }
    mouse_info = {
        "timestamp": time.time(),
        "mouse_data": mouse_data,
        "mouse_click_positions": mouse_click_positions,
        "mouse_movements": mouse_movements,
        "mouse_left_clicks": MouseStats.left_clicks,
        "mouse_right_clicks": MouseStats.right_clicks,
        "mouse_middle_clicks": MouseStats.middle_clicks,
        "mouse_scroll_count": MouseStats.scroll_count,
        "mouse_total_distance": MouseStats.total_distance
    }
    screentime_info = {
        "timestamp": time.time(),
        "screen_time_data": screen_time_data,
        "app_usage": app_usage
    }
    words_info = {
        "timestamp": time.time(),
        "word_usage": dict(word_usage),
        "word_daily_count": word_daily_count
    }
    streaks_info = {
        "timestamp": time.time(),
        "app_streaks": app_streaks,
        "apps_used_today": list(apps_used_today),
        "apps_used_yesterday": list(apps_used_yesterday),
        "last_streak_date": last_streak_date
    }
    if word_usage:
        valid_words = {w: cnt for w, cnt in word_usage.items() if cnt >=20 and w.isalpha() and len(w) >= 3}
        if valid_words:
            most_typed = max(valid_words, key=lambda k: valid_words[k])
            least_typed = min(valid_words, key=lambda k: valid_words[k])
        else:
            most_typed = ""
            least_typed = ""
    else:
        most_typed = ""
        least_typed = ""
    misc_info = {
        "timestamp": time.time(),
        "curse_general_count": curse_general_count,
        "racial_slurs_count": racial_slurs_count,
        "fastest_wpm": fastest_wpm,
        "current_word": current_word,
        "app_start_time": app_start_time,
        "most_typed_word": most_typed,
        "least_typed_word": least_typed
    }
    append_record("keyboard", keyboard_data)
    append_record("mouse", mouse_info)
    append_record("screentime", screentime_info)
    append_record("words", words_info)
    append_record("streaks", streaks_info)
    append_record("misc", misc_info)
def periodic_data_update():
    save_data()
    safe_after(60000, periodic_data_update)
def load_data():
    global key_usage, total_key_count, key_press_duration
    global mouse_data, mouse_click_positions, mouse_movements
    global screen_time_data, app_usage
    global word_usage, word_daily_count
    global app_streaks, apps_used_today, apps_used_yesterday, last_streak_date
    global curse_general_count, racial_slurs_count, fastest_wpm, current_word, app_start_time
    kd = load_latest_record("keyboard")
    if kd:
        key_usage = kd.get("key_usage", {})
        total_key_count = kd.get("total_key_count", 0)
        key_press_duration = kd.get("key_press_duration", {})
    md = load_latest_record("mouse")
    if md:
        mouse_data.update(md.get("mouse_data", {}))
        mouse_click_positions.update(md.get("mouse_click_positions", {}))
        mouse_movements.extend(md.get("mouse_movements", []))
        MouseStats.left_clicks = md.get("mouse_left_clicks", 0)
        MouseStats.right_clicks = md.get("mouse_right_clicks", 0)
        MouseStats.middle_clicks = md.get("mouse_middle_clicks", 0)
        MouseStats.scroll_count = md.get("mouse_scroll_count", 0)
        MouseStats.total_distance = md.get("mouse_total_distance", 0.0)
    st = load_latest_record("screentime")
    if st:
        screen_time_data.update(st.get("screen_time_data", {}))
        app_usage.update(st.get("app_usage", {}))
    wd = load_latest_record("words")
    if wd:
        word_usage.update(wd.get("word_usage", {}))
        word_daily_count.update(wd.get("word_daily_count", {}))
    sd_rec = load_latest_record("streaks")
    if sd_rec:
        app_streaks.update(sd_rec.get("app_streaks", {}))
        apps_used_today = set(sd_rec.get("apps_used_today", []))
        apps_used_yesterday = set(sd_rec.get("apps_used_yesterday", []))
        last_streak_date = sd_rec.get("last_streak_date", time.strftime("%Y-%m-%d"))
    misc = load_latest_record("misc")
    if misc:
        curse_general_count = misc.get("curse_general_count", 0)
        racial_slurs_count = misc.get("racial_slurs_count", 0)
        fastest_wpm = misc.get("fastest_wpm", 0)
        current_word = misc.get("current_word", "")
        app_start_time = misc.get("app_start_time", app_start_time)
    else:
        save_data()
load_data()
periodic_data_update()
periodic_backup()
export_label_page = ctk.CTkLabel(export_frame, text="Export Data", font=("Poppins", 28, "bold"), text_color="white", fg_color="#121212")
export_label_page.pack(pady=(20,10))
export_format_var_page = ctk.StringVar(value="JSON")
export_format_menu_page = ctk.CTkOptionMenu(export_frame, values=["JSON", "TXT", "CSV"], variable=export_format_var_page, font=("Poppins", 14))
export_format_menu_page.pack(pady=5, padx=20, fill="x")
export_status_label_page = ctk.CTkLabel(export_frame, text="", font=("Poppins", 12), fg_color="#121212", text_color="white")
export_status_label_page.pack(pady=5, padx=20, fill="x")
def export_data():
    export_status_label_page.configure(text="exporting...")
    fmt = export_format_var_page.get()
    def do_export():
        data = {
            "timestamp": time.time(),
            "key_usage": key_usage,
            "total_key_count": total_key_count,
            "word_usage": dict(word_usage),
            "word_daily_count": word_daily_count,
            "curse_general_count": curse_general_count,
            "racial_slurs_count": racial_slurs_count,
            "app_start_time": app_start_time,
            "screen_time_data": screen_time_data,
            "mouse_left_clicks": MouseStats.left_clicks,
            "mouse_right_clicks": MouseStats.right_clicks,
            "mouse_middle_clicks": MouseStats.middle_clicks,
            "mouse_scroll_count": MouseStats.scroll_count,
            "mouse_total_distance": MouseStats.total_distance,
            "mouse_data": mouse_data,
            "mouse_click_positions": mouse_click_positions,
            "mouse_movements": mouse_movements,
            "app_usage": app_usage,
            "fastest_wpm": fastest_wpm,
            "current_word": current_word,
            "key_press_duration": key_press_duration,
            "app_streaks": app_streaks,
            "apps_used_today": list(apps_used_today),
            "apps_used_yesterday": list(apps_used_yesterday),
            "last_streak_date": last_streak_date
        }
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if fmt == "JSON":
            filename = os.path.join(downloads_dir, f"export_{timestamp_str}.json")
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        elif fmt == "TXT":
            filename = os.path.join(downloads_dir, f"export_{timestamp_str}.txt")
            with open(filename, "w", encoding="utf-8") as f:
                for key, value in data.items():
                    f.write(f"{key}: {value}\n")
        elif fmt == "CSV":
            filename = os.path.join(downloads_dir, f"export_{timestamp_str}.csv")
            with open(filename, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Key", "Value"])
                for key, value in data.items():
                    writer.writerow([key, json.dumps(value)])
        root.after(0, lambda: export_status_label_page.configure(text="export complete"))
    threading.Thread(target=do_export, daemon=True).start()
export_button_page = ctk.CTkButton(export_frame, text="Export", font=("Poppins", 18, "bold"), fg_color="#3E4A59", hover_color="#5A6775", corner_radius=10, command=export_data)
export_button_page.pack(pady=12, padx=20, fill="x")
switch_screen("Keyboard")
def show_window(icon, event):
    if app_running and root.winfo_exists():
        root.deiconify()
        root.state("zoomed")
def create_image():
    width = 64
    height = 64
    image = Image.new("RGB", (width, height), "gray")
    return image
tray_menu = pystray.Menu(pystray.MenuItem("Quit", quit_app))
tray_icon = pystray.Icon("OptimizedKeyboardUI", create_image(), "Optimized Keyboard UI", tray_menu)
tray_icon.on_clicked = show_window
threading.Thread(target=tray_icon.run, daemon=True).start()
try:
    root.mainloop()
except KeyboardInterrupt:
    on_closing()
