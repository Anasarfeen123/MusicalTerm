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

    if core.download_thumbnail(url, "cover.jpg"):
        px, w, h = core.get_album_art_matrix("cover.jpg", size=art_width - 4) # Adjust for padding
        with art_lock:
            art_data["pixels"] = px
            art_data["w"] = w
            art_data["h"] = h
    
    with art_lock:
        art_data["loading"] = False

def trigger_art_load(url, art_width):
    thread = threading.Thread(target=bg_update_art, args=(url, art_width), daemon=True)
    thread.start()

def draw_art(win, pixels, img_w, img_h):
    """
    High quality half-block renderer using foreground + background colors.
    Much smoother than single █ rendering.
    """

    if not pixels:
        return

    def rgb_to_256(r, g, b):
        return 16 + int(r/255*5)*36 + int(g/255*5)*6 + int(b/255*5)

    pair_cache = {}
    next_pair_id = 10  # Avoid clashing with UI color pairs

    for y in range(0, img_h - 1, 2):
        for x in range(img_w):

            top_idx = y * img_w + x
            bottom_idx = (y + 1) * img_w + x

            if top_idx >= len(pixels) or bottom_idx >= len(pixels):
                continue

            r1, g1, b1 = pixels[top_idx]
            r2, g2, b2 = pixels[bottom_idx]

            fg = rgb_to_256(r1, g1, b1)
            bg = rgb_to_256(r2, g2, b2)

            key = (fg, bg)

            if key not in pair_cache:
                if next_pair_id < curses.COLOR_PAIRS:
                    curses.init_pair(next_pair_id, fg, bg)
                    pair_cache[key] = next_pair_id
                    next_pair_id += 1
                else:
                    pair_cache[key] = 0  # fallback

            try:
                win.addch((y // 2) + 1, x + 1, "▀",
                          curses.color_pair(pair_cache[key]))
            except curses.error:
                pass
            
# -----------------------------
# UI COMPONENTS
# -----------------------------

def draw_progress_bar(win, y, x, width, progress):
    if width < 15: return
    bar_width = width - 12
    filled_len = int(progress * bar_width)
    # Using a mix of blocks and lines for a cleaner look
    bar = "━" * filled_len + "╌" * (bar_width - filled_len)
    percent = f" {int(progress * 100):3d}% "
    try:
        win.addstr(y, x, "┫", curses.color_pair(3))
        win.addstr(y, x + 1, bar, curses.color_pair(3) | curses.A_BOLD)
        win.addstr(y, x + bar_width + 1, "┣", curses.color_pair(3))
        win.addstr(y, x + bar_width + 3, percent, curses.A_BOLD)
    except curses.error: pass

def draw_header(win, banner, width):
    win.erase()
    for i, line in enumerate(banner):
        x = max(0, (width - len(line)) // 2)
        try:
            win.addstr(i, x, line, curses.color_pair(1) | curses.A_BOLD)
        except curses.error: pass
    win.refresh()

# -----------------------------
# MAIN UI LOOP
# -----------------------------

def run_ui(stdscr):
    # Colors & Setup
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    stdscr.nodelay(True)
    stdscr.keypad(True)
    
    # UI Color Pairs
    curses.init_pair(1, curses.COLOR_CYAN, -1)   # Header / Title
    curses.init_pair(2, curses.COLOR_YELLOW, -1) # Volume / Status
    curses.init_pair(3, curses.COLOR_GREEN, -1)  # Progress Bar
    curses.init_pair(4, curses.COLOR_WHITE, 235) # Footer Style
    
    height, width = stdscr.getmaxyx()
    if height < 24 or width < 85:
        stdscr.addstr(0, 0, f"Terminal too small ({width}x{height}). Need 85x24.")
        stdscr.refresh()
        curses.napms(2000)
        return

    banner = f.renderText("MusicalTerm").splitlines()
    banner_h = len(banner)

    # Dynamic Layout Calculation
    art_w, art_h = 42, 20
    p_h, p_w = 10, min(width - art_w - 8, 50)
    
    total_ui_w = art_w + p_w + 4
    start_x = (width - total_ui_w) // 2

    header_win = curses.newwin(banner_h + 1, width, 1, 0)
    art_win = curses.newwin(art_h, art_w, banner_h + 2, start_x)
    player_win = curses.newwin(p_h, p_w, banner_h + (art_h - p_h) // 2 + 2, start_x + art_w + 2)
    footer_win = curses.newwin(2, width, height - 2, 0)

    draw_header(header_win, banner, width)
    
    # Initial Data Load
    url = "https://music.youtube.com/playlist?list=PLF09LSCsr9VMLI8WhNk9Mu7dYawruYBDi"
    media = core.extract_media(url)
    if not media or not media.get("tracks"):
        stdscr.addstr(height // 2, (width // 2) - 10, "FAILED TO LOAD MEDIA", curses.color_pair(2))
        stdscr.refresh()
        curses.napms(2000)
        return

    queue = media["tracks"]
    current_idx, volume = 0, 50
    spinner = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    spin_idx = 0

    def start_track(idx):
        track = queue[idx]
        player.play_stream(track["url"])
        trigger_art_load(track["url"], art_w)
        return track["title"]

    current_title = start_track(current_idx)

    while True:
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
        elif key in [ord("p"), ord("r")]:
            player.pause_stream() if key == ord("p") else player.resume_stream()
        elif key == curses.KEY_UP:
            volume = min(100, volume + 5)
            player.set_volume(volume)
        elif key == curses.KEY_DOWN:
            volume = max(0, volume - 5)
            player.set_volume(volume)
        elif key == curses.KEY_RIGHT: player.seek(10)
        elif key == curses.KEY_LEFT: player.seek(-10)

        # Draw Art
        art_win.erase()
        art_win.attron(curses.color_pair(1))
        art_win.border()
        art_win.attroff(curses.color_pair(1))
        art_win.addstr(0, 2, " ALBUM ART ", curses.A_BOLD)
        with art_lock:
            if art_data["loading"]:
                art_win.addstr(art_h // 2, (art_w // 2) - 5, f"{spinner[spin_idx%10]} Loading...")
            elif art_data["pixels"]:
                draw_art(art_win, art_data["pixels"], art_data["w"], art_data["h"])
            else:
                art_win.addstr(art_h // 2, (art_w // 2) - 7, "No Thumbnail")
        art_win.refresh()

        # Draw Player
        player_win.erase()
        player_win.attron(curses.color_pair(1))
        player_win.border()
        player_win.attroff(curses.color_pair(1))
        player_win.addstr(0, 2, " PLAYER ", curses.A_BOLD)

        clean_title = (current_title[:p_w-6] + '..') if len(current_title) > p_w-6 else current_title
        player_win.addstr(2, 3, clean_title, curses.color_pair(1) | curses.A_BOLD)
        
        vol_str = f"VOL: {volume}%"
        player_win.addstr(4, 3, vol_str, curses.color_pair(2))

        elapsed = player.get_position()
        duration = player.get_duration()

        if elapsed is not None and duration and duration > 0:
            m_e, s_e = divmod(int(elapsed), 60)
            m_t, s_t = divmod(int(duration), 60)
            player_win.addstr(4, p_w - 14, f"{m_e:02}:{s_e:02}/{m_t:02}:{s_t:02}")
            draw_progress_bar(player_win, 7, 3, p_w - 6, min(1.0, elapsed / duration))
        else:
            player_win.addstr(7, 3, f"{spinner[spin_idx % 10]} Buffering...", curses.A_DIM)

        player_win.refresh()

        # Draw Footer
        footer_win.erase()
        help_text = " [Q]uit  [P]ause  [R]esume  [N]ext  [B]ack  [↑/↓] Vol  [←/→] Seek "
        footer_win.addstr(0, (width - len(help_text)) // 2, help_text, curses.color_pair(4))
        footer_win.refresh()

        spin_idx += 1
        curses.napms(100)

if __name__ == "__main__":
    curses.wrapper(run_ui)