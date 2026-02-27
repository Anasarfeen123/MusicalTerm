import curses
import threading
from pyfiglet import Figlet
import core
import player

# Initialize Figlet once
f = Figlet(font="future")

# Global state for background art loading
art_lock = threading.Lock()
art_data = {"pixels": None, "w": 0, "h": 0, "loading": False}

# -----------------------------
# ART LOADING (THREADED)
# -----------------------------

def bg_update_art(url, art_width):
    global art_data
    with art_lock:
        art_data["loading"] = True
        art_data["pixels"] = None

    # Download and process the thumbnail
    if core.download_thumbnail(url, "cover.jpg"):
        px, w, h = core.get_album_art_matrix("cover.jpg", size=art_width - 2)
        with art_lock:
            art_data["pixels"] = px
            art_data["w"] = w
            art_data["h"] = h
    
    with art_lock:
        art_data["loading"] = False

def trigger_art_load(url, art_width):
    thread = threading.Thread(
        target=bg_update_art,
        args=(url, art_width),
        daemon=True
    )
    thread.start()

def draw_art(win, pixels, img_w, img_h):
    if not pixels:
        return

    # Use a try-except block to handle terminal limits gracefully
    for y in range(img_h):
        for x in range(img_w):
            idx = y * img_w + x
            if idx >= len(pixels): break
            
            r, g, b = pixels[idx]

            # Map RGB to 256-color palette (xterm)
            color_idx = 16 + int(r/255*5)*36 + int(g/255*5)*6 + int(b/255*5)
            # Use color_idx as the pair_id for simplicity in this TUI
            pair_id = (color_idx % 254) + 1
            curses.init_pair(pair_id, color_idx, -1)

            try:
                win.addch(y + 1, x + 1, "█", curses.color_pair(pair_id))
            except curses.error:
                pass

# -----------------------------
# UI COMPONENTS
# -----------------------------

def draw_progress_bar(win, y, x, width, progress):
    if width < 10: return
    
    label = f" {int(progress * 100):3d}% "
    bar_width = width - len(label) - 2
    filled_len = int(progress * bar_width)
    
    bar = "█" * filled_len + "░" * (bar_width - filled_len)
    
    try:
        win.addstr(y, x, bar, curses.A_BOLD)
        win.addstr(y, x + bar_width + 1, label)
    except curses.error:
        pass

def draw_header(win, banner, width):
    win.erase()
    for i, line in enumerate(banner):
        x = max(0, (width - len(line)) // 2)
        try:
            win.addstr(i, x, line[:width - 1], curses.A_BOLD | curses.color_pair(2))
        except curses.error:
            pass
    win.refresh()

# -----------------------------
# MAIN UI LOOP
# -----------------------------

def run_ui(stdscr):
    # Initial Curses Setup
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    stdscr.nodelay(True)
    stdscr.keypad(True)
    
    # Simple color pairs for UI elements
    curses.init_pair(255, curses.COLOR_CYAN, -1) # Header
    
    height, width = stdscr.getmaxyx()
    if height < 24 or width < 80:
        stdscr.addstr(0, 0, "Terminal too small! Please resize to at least 80x24.")
        stdscr.refresh()
        curses.napms(2000)
        return

    banner = f.renderText("MusicalTerm").splitlines()
    banner_h = len(banner)

    # Windows Layout
    header_win = curses.newwin(banner_h + 1, width, 0, 0)
    
    art_w, art_h = 40, 18
    art_y, art_x = banner_h + 1, 2
    art_win = curses.newwin(art_h, art_w, art_y, art_x)

    p_h = 10
    p_w = min(width - art_w - 6, 80)
    p_y, p_x = art_y + (art_h - p_h) // 2, art_x + art_w + 2
    player_win = curses.newwin(p_h, p_w, p_y, p_x)

    footer_win = curses.newwin(2, width, height - 2, 0)

    # Load Playlist
    draw_header(header_win, banner, width)
    stdscr.refresh()

    url = "https://music.youtube.com/playlist?list=PLF09LSCsr9VMLI8WhNk9Mu7dYawruYBDi"
    media = core.extract_media(url)

    if not media or not media.get("tracks"):
        stdscr.clear()
        stdscr.addstr(height // 2, width // 2 - 10, "FAILED TO LOAD MEDIA")
        stdscr.refresh()
        curses.napms(2000)
        return

    queue = media["tracks"]
    current_idx = 0
    volume = 50
    spinner = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    spin_idx = 0

    def start_track(idx):
        track = queue[idx]
        player.play_stream(track["url"])
        trigger_art_load(track["url"], art_w)
        return track["title"]

    current_title = start_track(current_idx)

    while True:
        # 1. Handle Input
        key = stdscr.getch()
        if key == ord("q"):
            player.stop_stream()
            break
        elif key == ord("n") and current_idx + 1 < len(queue):
            current_idx += 1
            current_title = start_track(current_idx)
        elif key == ord("b") and current_idx > 0:
            current_idx -= 1
            current_title = start_track(current_idx)
        elif key == ord("p"):
            player.pause_stream()
        elif key == ord("r"):
            player.resume_stream()
        elif key == curses.KEY_UP:
            volume = min(100, volume + 5)
            player.set_volume(volume)
        elif key == curses.KEY_DOWN:
            volume = max(0, volume - 5)
            player.set_volume(volume)
        elif key == curses.KEY_RIGHT:
            player.seek(10)
        elif key == curses.KEY_LEFT:
            player.seek(-10)

        # 2. Get Player State
        elapsed = player.get_position()
        duration = player.get_duration()

        # 3. Draw Art Window
        art_win.erase()
        art_win.box()
        art_win.addstr(0, 2, " ALBUM ART ", curses.A_BOLD)
        
        with art_lock:
            if art_data["loading"]:
                art_win.addstr(art_h // 2, (art_w // 2) - 5, "Loading...")
            elif art_data["pixels"]:
                draw_art(art_win, art_data["pixels"], art_data["w"], art_data["h"])
            else:
                art_win.addstr(art_h // 2, (art_w // 2) - 7, "No Thumbnail")
        art_win.refresh()

        # 4. Draw Player Window
        player_win.erase()
        player_win.box()
        player_win.addstr(0, 2, " NOW PLAYING ", curses.A_BOLD)

        # Truncate title if too long
        display_title = (current_title[:p_w-10] + '..') if len(current_title) > p_w-10 else current_title
        player_win.addstr(2, 4, display_title, curses.A_BOLD | curses.color_pair(255))
        
        # Volume Indicator
        player_win.addstr(2, p_w - 12, f"VOL: {volume}%")

        if elapsed is not None and duration and duration > 0:
            m_e, s_e = divmod(int(elapsed), 60)
            m_t, s_t = divmod(int(duration), 60)
            time_str = f"{m_e:02}:{s_e:02} / {m_t:02}:{s_t:02}"
            player_win.addstr(4, 4, time_str)
            draw_progress_bar(player_win, 6, 4, p_w - 8, min(1.0, elapsed / duration))
        else:
            player_win.addstr(6, 4, f"{spinner[spin_idx % len(spinner)]} Initializing Stream...")

        player_win.refresh()

        # 5. Draw Footer (Controls Help)
        footer_win.erase()
        help_text = " [Q]uit | [P]ause | [R]esume | [N]ext | [B]ack | [↑/↓] Vol | [←/→] Seek "
        footer_win.addstr(0, max(0, (width - len(help_text)) // 2), help_text, curses.A_REVERSE)
        footer_win.refresh()

        spin_idx += 1
        curses.napms(100) # 10 FPS Refresh rate