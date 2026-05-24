"""
MusicalTerm — Terminal Music Player
Aesthetic: Dark obsidian / warm amber & rose accents
"""

import curses
import threading
import random
import time
import os
import tempfile
import math
from pyfiglet import Figlet
import core
import player

# ─── Fonts ────────────────────────────────────────────────────────────────────
try:
    f_title = Figlet(font="banner3-D")
except Exception:
    f_title = Figlet(font="banner")

# ─── Design Tokens ────────────────────────────────────────────────────────────
CHARS = {
    "bar_fill":    "█",
    "bar_empty":   "░",
    "vol_fill":    "▰",
    "vol_empty":   "▱",
    "h_line":      "━",
    "v_line":      "┃",
    "tl":          "╭",
    "tr":          "╮",
    "bl":          "╰",
    "br":          "╯",
    "t_left":      "├",
    "t_right":     "┤",
    "play":        "▶",
    "pause":       "⏸",
    "shuffle_on":  "⇄",
    "shuffle_off": "⇒",
    "repeat_on":   "↺",
    "repeat_off":  "↷",
    "mute":        "✕",
    "vol":         "♪",
    "dot":         "·",
    "arrow":       "›",
    "bullet":      "◆",
    "dim_bullet":  "◇",
    "spin":        ["◐", "◓", "◑", "◒"],
}

# ─── Color Palette ────────────────────────────────────────────────────────────
# Static theme: warm amber / deep rose / slate

# Color pair IDs
C_ACCENT  = 1   # Primary accent — warm amber
C_DIM     = 2   # Muted foreground
C_WHITE   = 3   # Bright white
C_GREEN   = 4   # Volume / progress fill
C_TITLE   = 5   # Header title
C_STATUS  = 6   # Status / warning
C_QUEUE_H = 7   # Queue highlight
C_ART_BG  = 8   # Art panel border (set per-album by dominant color)
C_CYAN    = 9   # Secondary accent — rose/salmon
C_MAGENTA = 10  # Tertiary accent — soft lavender

# ─── Art Helpers ─────────────────────────────────────────────────────────────

def to256(r, g, b):
    """Accurate RGB to 256-color terminal index mapping."""
    # Grayscale ramp
    if abs(r - g) < 4 and abs(g - b) < 4:
        if r < 8: return 16
        if r > 248: return 231
        return 232 + (r - 8) // 10
    
    # 6x6x6 Color Cube
    def q(x):
        if x < 48: return 0
        if x < 115: return 1
        if x < 155: return 2
        if x < 195: return 3
        if x < 235: return 4
        return 5
    
    return 16 + q(r)*36 + q(g)*6 + q(b)

# ─── Art State ────────────────────────────────────────────────────────────────
art_lock = threading.Lock()
art_data = {
    "pixels": None, 
    "w": 0, "h": 0, 
    "loading": False, 
    "dom_idx": 51,
    "pairs": {},    # (fg, bg) -> pair_idx
    "nxt_pair": 200 # Start safe from theme colors
}


# ─── State ────────────────────────────────────────────────────────────────────
class State:
    def __init__(self):
        self.queue          = []
        self.shuffle_pool   = []  # remaining unplayed indices for true shuffle
        self.history        = []
        self.current_idx    = 0
        self.queue_cursor   = 0
        self.volume         = 70
        self.paused         = False
        self.repeat         = False
        self.shuffle        = False
        self.muted          = False
        self.view           = "player"
        self.queue_offset   = 0
        self.filter_text    = ""
        self.filter_mode    = False
        self.favorites      = set()
        self.favorites_only = False
        self.help_open      = False
        self.theme_idx      = 0
        self.media_title    = ""
        self.media_type     = ""
        self._status_msg    = ""
        self._status_ts     = 0
        self.spin_idx       = 0

    def set_status(self, msg, ttl=3.0):
        self._status_msg = msg
        self._status_ts  = time.time() + ttl

    def get_status(self):
        return self._status_msg if time.time() < self._status_ts else ""

    def reset_shuffle_pool(self):
        """Rebuild the shuffle pool excluding the current track."""
        self.shuffle_pool = [i for i in range(len(self.queue)) if i != self.current_idx]
        random.shuffle(self.shuffle_pool)

    def next_idx(self):
        if not self.queue:
            return 0
        if self.shuffle:
            # True no-repeat shuffle: drain pool, refill when empty
            if not self.shuffle_pool:
                self.reset_shuffle_pool()
            if self.shuffle_pool:
                return self.shuffle_pool.pop(0)
            return self.current_idx
        return (self.current_idx + 1) % len(self.queue)

    def visible_indices(self):
        items = []
        needle = self.filter_text.lower().strip()
        for idx, track in enumerate(self.queue):
            if self.favorites_only and idx not in self.favorites:
                continue
            title = (track.get("title") or "").lower()
            artist = (track.get("uploader") or "").lower()
            if needle and needle not in title and needle not in artist:
                continue
            items.append(idx)
        return items

    def sync_cursor_to_current(self):
        self.queue_cursor = self.current_idx


# ─── Animation Data ───────────────────────────────────────────────────────────
DANCER_FRAMES = [
    [
        "   o   ",
        "  /|\\  ",
        "  / \\  "
    ],
    [
        "  \\o/  ",
        "   |   ",
        "  / \\  "
    ],
    [
        "  _o_  ",
        " / | \\ ",
        "  / \\  "
    ],
    [
        "   o   ",
        "  /|\\_ ",
        "  /    "
    ],
    [
        "  _o   ",
        "   |\\  ",
        "  / \\  "
    ]
]

# ─── Art Loading ──────────────────────────────────────────────────────────────

def _bg_load_art(url, art_w, art_h):
    global art_data
    with art_lock:
        art_data["loading"] = True

    cover_path = os.path.join(tempfile.gettempdir(), f"musicalterm_cover_{os.getpid()}.jpg")
    if core.download_thumbnail(url, cover_path):
        px, w, h, dom_rgb = core.get_album_art_matrix(cover_path, max_w=art_w-4, max_h=art_h-4)
        if px:
            indices = [to256(r, g, b) for r, g, b in px]
            dom_idx = to256(*dom_rgb)

            with art_lock:
                art_data.update(pixels=indices, w=w, h=h, dom_idx=dom_idx)
                art_data["pairs"] = {}
                art_data["nxt_pair"] = 200

    with art_lock:
        art_data["loading"] = False


def trigger_art_load(url, art_w, art_h):
    threading.Thread(target=_bg_load_art, args=(url, art_w, art_h), daemon=True).start()


def draw_art(win, indices, img_w, img_h, st=None):
    """Renders a dancing ASCII character tinted with the album's dominant color."""
    win_h, win_w = win.getmaxyx()
    
    with art_lock:
        dom_idx = art_data.get("dom_idx", 214)
    
    accent = curses.color_pair(C_ART_BG)
    dim = curses.color_pair(C_DIM)
    
    # Calculate animation frame based on state spin index
    frame_idx = (st.spin_idx // 2) % len(DANCER_FRAMES) if st else 0
    frame = DANCER_FRAMES[frame_idx]
    
    fh = len(frame)
    fw = len(frame[0])
    
    start_y = (win_h - fh) // 2
    start_x = (win_w - fw) // 2
    
    # Draw a small "stage" or glow
    for dy in range(-1, fh + 1):
        for dx in range(-4, fw + 4):
            if 0 < start_y + dy < win_h - 1 and 0 < start_x + dx < win_w - 1:
                if dy == fh:
                    S(win, start_y + dy, start_x + dx, "▔", dim)
                elif dy >= 0 and dy < fh:
                    # Subtle background aura using dominant color
                    if random.random() > 0.92:
                        S(win, start_y + dy, start_x + dx, "·", dim)

    # Draw the dancer
    for i, line in enumerate(frame):
        # We can alternate colors for a "disco" effect if we want, 
        # but let's stick to the dominant accent first.
        attr = accent | curses.A_BOLD
        if i == 0: attr |= curses.A_REVERSE # Head highlight
        S(win, start_y + i, start_x, line, attr)
    
    # Add some "musical notes" popping up
    notes = ["♪", "♫", "♩", "♬"]
    if st and st.spin_idx % 4 == 0:
        ny = start_y - 1 - (st.spin_idx % 3)
        nx = start_x + (st.spin_idx % fw)
        if 0 < ny < win_h:
            S(win, ny, nx, random.choice(notes), accent)


# ─── Primitives ───────────────────────────────────────────────────────────────

def S(win, y, x, text, attr=0):
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


def draw_box(win, h, w, cp):
    c = CHARS
    S(win, 0,   0,   c["tl"] + c["h_line"]*(w-2) + c["tr"], cp)
    S(win, h-1, 0,   c["bl"] + c["h_line"]*(w-2) + c["br"], cp)
    for r in range(1, h-1):
        S(win, r, 0,   c["v_line"], cp)
        S(win, r, w-1, c["v_line"], cp)


def draw_hrule(win, y, x, w, cp):
    S(win, y, x,     CHARS["t_left"],         cp)
    S(win, y, x+1,   CHARS["h_line"]*(w-2),   cp)
    S(win, y, x+w-1, CHARS["t_right"],         cp)


def panel_label(win, text, w, cp):
    label = f"  {text}  "
    S(win, 0, max(2, (w - len(label))//2), label, cp | curses.A_BOLD)


def trunc(s, n):
    return (s[:n-1] + "…") if len(s) > n else s


def fmt_t(s):
    if s is None:
        return "--:--"
    m, sec = divmod(int(s), 60)
    return f"{m:02}:{sec:02}"


def track_duration(track):
    return track.get("duration")


def total_duration(queue):
    vals = [t.get("duration") for t in queue if t.get("duration")]
    return sum(vals) if vals else None


THEMES = [
    {
        "name": "ember",
        "accent": 214,
        "dim": 238,
        "white": 255,
        "green": 150,
        "title": 214,
        "status": 203,
        "queue": 214,
        "art": 94,
        "cyan": 216,
        "magenta": 183,
    },
    {
        "name": "neon",
        "accent": 81,
        "dim": 244,
        "white": 255,
        "green": 118,
        "title": 45,
        "status": 203,
        "queue": 81,
        "art": 33,
        "cyan": 159,
        "magenta": 213,
    },
    {
        "name": "mono",
        "accent": 250,
        "dim": 240,
        "white": 255,
        "green": 248,
        "title": 255,
        "status": 209,
        "queue": 250,
        "art": 245,
        "cyan": 252,
        "magenta": 247,
    },
]


def apply_theme(st):
    theme = THEMES[st.theme_idx % len(THEMES)]
    curses.init_pair(C_ACCENT,  theme["accent"],  -1)
    curses.init_pair(C_DIM,     theme["dim"],     -1)
    curses.init_pair(C_WHITE,   theme["white"],   -1)
    curses.init_pair(C_GREEN,   theme["green"],   -1)
    curses.init_pair(C_TITLE,   theme["title"],   -1)
    curses.init_pair(C_STATUS,  theme["status"],  -1)
    curses.init_pair(C_QUEUE_H, theme["queue"],   -1)
    curses.init_pair(C_ART_BG,  theme["art"],     -1)
    curses.init_pair(C_CYAN,    theme["cyan"],    -1)
    curses.init_pair(C_MAGENTA, theme["magenta"], -1)


def render_help_overlay(stdscr, st):
    h, w = stdscr.getmaxyx()
    box_w = min(74, w - 4)
    box_h = min(18, h - 4)
    y = max(1, (h - box_h) // 2)
    x = max(1, (w - box_w) // 2)
    win = curses.newwin(box_h, box_w, y, x)
    accent = curses.color_pair(C_ACCENT)
    dim = curses.color_pair(C_DIM)
    white = curses.color_pair(C_WHITE)
    stat = curses.color_pair(C_STATUS)

    win.erase()
    draw_box(win, box_h, box_w, accent)
    panel_label(win, "K E Y S", box_w, accent)

    rows = [
        ("Space", "play / pause"),
        ("N / B", "next / previous"),
        ("S / L / M", "shuffle / repeat / mute"),
        ("Up Down", "volume or queue movement"),
        ("Left Right", "seek -10s / +10s"),
        ("Tab", "player / queue"),
        ("/", "filter queue"),
        ("F", "favorite current or highlighted track"),
        ("A", "show all / favorites only"),
        ("T", f"theme: {THEMES[st.theme_idx % len(THEMES)]['name']}"),
        ("?", "close help"),
        ("Q", "quit"),
    ]
    col_w = max(20, (box_w - 6) // 2)
    for i, (key, label) in enumerate(rows[:box_h-4]):
        row = 2 + i
        S(win, row, 3, trunc(key, col_w - 2), white | curses.A_BOLD)
        S(win, row, col_w, trunc(label, box_w - col_w - 3), dim)

    S(win, box_h - 2, 3, "Tip: paste a URL or type a search query at launch.", stat | curses.A_DIM)
    win.refresh()


# ─── URL Input Screen ─────────────────────────────────────────────────────────

def get_url_input(stdscr):
    """
    Full-screen URL/link entry before the player starts.
    Returns the entered URL string, or None to quit.
    """
    curses.curs_set(1)
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    gold  = curses.color_pair(C_ACCENT)
    dim   = curses.color_pair(C_DIM)
    white = curses.color_pair(C_WHITE)
    stat  = curses.color_pair(C_STATUS)

    banner = f_title.renderText("MT").splitlines()

    # Draw header
    for i, line in enumerate(banner):
        S(stdscr, i, max(0, (width - len(line))//2), line, gold | curses.A_BOLD)

    cy = len(banner) + 2

    title_line = "  ♪  Paste a YouTube URL or type a search  ♪  "
    S(stdscr, cy, max(0, (width - len(title_line))//2), title_line, white | curses.A_BOLD)
    cy += 2

    hint_lines = [
        "Supported input:",
        "  • Single video   → https://www.youtube.com/watch?v=...",
        "  • Playlist       → https://www.youtube.com/playlist?list=...",
        "  • YT Music song  → https://music.youtube.com/watch?v=...",
        "  • Search query   → boards of canada roygbiv",
        "",
        "Press ENTER to confirm  ·  ESC or Ctrl+C to quit",
    ]
    for line in hint_lines:
        S(stdscr, cy, max(0, (width - 56)//2), line, dim)
        cy += 1

    cy += 1
    box_w  = min(72, width - 6)
    box_x  = max(0, (width - box_w)//2)
    prompt = " Play › "

    # Input box border
    S(stdscr, cy,   box_x, CHARS["tl"] + CHARS["h_line"]*(box_w-2) + CHARS["tr"], gold)
    S(stdscr, cy+1, box_x, CHARS["v_line"], gold)
    S(stdscr, cy+1, box_x+box_w-1, CHARS["v_line"], gold)
    S(stdscr, cy+2, box_x, CHARS["bl"] + CHARS["h_line"]*(box_w-2) + CHARS["br"], gold)

    S(stdscr, cy+1, box_x+1, prompt, gold | curses.A_BOLD)
    stdscr.refresh()

    buf     = ""
    input_x = box_x + 1 + len(prompt)
    input_w = box_w - 2 - len(prompt)
    err_y   = cy + 4

    while True:
        # Render buffer
        display = buf[-(input_w-1):] if len(buf) >= input_w else buf
        S(stdscr, cy+1, input_x, " " * input_w, 0)
        S(stdscr, cy+1, input_x, display, white)
        stdscr.move(cy+1, input_x + min(len(buf), input_w-1))
        stdscr.refresh()

        try:
            ch = stdscr.get_wch()
        except Exception:
            continue

        if isinstance(ch, str):
            if ch == "\n":
                url = buf.strip()
                if url:
                    curses.curs_set(0)
                    return url
                S(stdscr, err_y, box_x, " Please enter a URL or search before pressing Enter. ", stat)
                stdscr.refresh()
            elif ch == "\x1b":     # ESC
                curses.curs_set(0)
                return None
            elif ch == "\x03":     # Ctrl+C
                curses.curs_set(0)
                return None
            elif ch in ("\x08", "\x7f"):  # Backspace
                buf = buf[:-1]
                S(stdscr, err_y, box_x, " " * 50, 0)
            elif len(ch) == 1 and ord(ch) >= 32:
                buf += ch
        elif isinstance(ch, int):
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                buf = buf[:-1]
                S(stdscr, err_y, box_x, " " * 50, 0)
            elif ch == curses.KEY_ENTER:
                url = buf.strip()
                if url:
                    curses.curs_set(0)
                    return url


# ─── Panels ───────────────────────────────────────────────────────────────────

def render_art_panel(win, st, art_w, art_h):
    win.erase()
    with art_lock:
        dom_idx = art_data.get("dom_idx", 214)

    # Re-init dominant color in main thread for safety
    try:
        curses.init_pair(C_ART_BG, dom_idx, -1)
        curses.init_pair(C_QUEUE_H, dom_idx, -1)
    except:
        pass

    border_color = curses.color_pair(C_ART_BG)
    dim          = curses.color_pair(C_DIM)

    draw_box(win, art_h, art_w, border_color)
    panel_label(win, "A L B U M", art_w, border_color)

    with art_lock:
        loading = art_data["loading"]
        pixels  = art_data["pixels"]
        iw, ih  = art_data["w"], art_data["h"]

    if loading:
        sp = CHARS["spin"][st.spin_idx % 4]
        S(win, art_h//2, (art_w-12)//2, f" {sp}  loading… ", dim)
    elif pixels:
        draw_art(win, pixels, iw, ih, st)
    else:
        # ─── Improved Vinyl Aesthetic ───
        cy, cx = art_h // 2, art_w // 2
        r = min(art_h, art_w) // 3
        
        # Draw grooves
        for i in range(r, r-4, -1):
            if i <= 0: continue
            for angle in range(0, 360, 10):
                rad = math.radians(angle)
                y = int(cy + (i * 0.5) * math.sin(rad))
                x = int(cx + (i * 1.1) * math.cos(rad))
                if 0 < y < art_h-1 and 0 < x < art_w-1:
                    win.addch(y, x, "·", dim)

        # Record Label
        S(win, cy, cx-3, "  ●  ", border_color | curses.A_BOLD)
        S(win, cy-1, cx-3, " .-. ", dim)
        S(win, cy+1, cx-3, " '-' ", dim)
        S(win, cy, cx-1, "VINYL", border_color | curses.A_BOLD | curses.A_REVERSE)
    win.refresh()


def render_player_panel(win, st, p_w, p_h):
    win.erase()
    accent = curses.color_pair(C_ACCENT)
    dim    = curses.color_pair(C_DIM)
    white  = curses.color_pair(C_WHITE)
    grn    = curses.color_pair(C_GREEN)
    stat   = curses.color_pair(C_STATUS)
    cyan   = curses.color_pair(C_CYAN)
    mag    = curses.color_pair(C_MAGENTA)
    iw     = p_w - 4

    draw_box(win, p_h, p_w, accent)
    panel_label(win, "N O W  P L A Y I N G", p_w, accent)

    track   = st.queue[st.current_idx] if st.queue else None
    title   = track["title"] if track else "No track loaded"
    artist  = track.get("uploader") if track else None
    counter = f"{st.current_idx+1:02}/{len(st.queue):02}"
    fav = "♥ " if st.current_idx in st.favorites else ""
    display_title = f"{fav}❖ {trunc(title, iw - len(counter) - len(fav) - 6)}"
    S(win, 2, 2, display_title, accent | curses.A_BOLD)
    S(win, 2, p_w - len(counter) - 2, counter, dim)

    draw_hrule(win, 3, 0, p_w, accent)

    # Mode flags — distinct colors per state
    cx = 2
    if st.paused:
        seg = f"{CHARS['pause']} PAUSED  "
        S(win, 4, cx, seg, stat | curses.A_BOLD)
    else:
        seg = f"{CHARS['play']} PLAYING  "
        S(win, 4, cx, seg, white | curses.A_BOLD)
    cx += len(seg)

    # Shuffle — cyan when on
    shuf_icon = CHARS["shuffle_on"] if st.shuffle else CHARS["shuffle_off"]
    shuf_attr = cyan | curses.A_BOLD if st.shuffle else dim
    shuf_seg  = f"{shuf_icon} SHUFFLE  "
    S(win, 4, cx, shuf_seg, shuf_attr)
    cx += len(shuf_seg)

    # Repeat — magenta when on
    rep_icon = CHARS["repeat_on"] if st.repeat else CHARS["repeat_off"]
    rep_attr = mag | curses.A_BOLD if st.repeat else dim
    rep_seg  = f"{rep_icon} REPEAT  "
    S(win, 4, cx, rep_seg, rep_attr)
    cx += len(rep_seg)

    # Mute — red when on
    if st.muted:
        S(win, 4, cx, f"{CHARS['mute']} MUTED  ", stat | curses.A_BOLD)

    # Shuffle pool indicator
    if st.shuffle and st.queue:
        remaining = len(st.shuffle_pool)
        total     = len(st.queue)
        shuf_info = f"[{remaining}/{total}]"
        S(win, 4, p_w - len(shuf_info) - 2, shuf_info, cyan | curses.A_DIM)

    draw_hrule(win, 5, 0, p_w, accent)

    meta_y = 6
    if artist:
        S(win, meta_y, 2, trunc(f"by {artist}", iw), dim)
    else:
        S(win, meta_y, 2, trunc(st.media_title or "streaming from YouTube", iw), dim)

    known_total = total_duration(st.queue)
    cur_dur = track_duration(track) if track else None
    stats = []
    if st.media_type:
        stats.append(st.media_type.upper())
    if cur_dur:
        stats.append(f"track {fmt_t(cur_dur)}")
    if known_total:
        stats.append(f"set {fmt_t(known_total)}")
    if st.favorites:
        stats.append(f"{len(st.favorites)} favorites")
    if stats:
        S(win, meta_y + 1, 2, trunc("  ·  ".join(stats), iw), cyan | curses.A_DIM)

    # Volume bar — green→cyan gradient feel
    vbw   = iw - 10
    vfill = round((st.volume / 100) * vbw)
    vbar  = CHARS["vol_fill"]*vfill + CHARS["vol_empty"]*(vbw-vfill)
    vlabel = f"{CHARS['vol']} {st.volume:3d}%"
    S(win, 9, 2, vlabel, accent | curses.A_BOLD)
    half = max(0, vbw // 2)
    S(win, 9, 2 + len(vlabel) + 1, vbar[:half], grn)
    S(win, 9, 2 + len(vlabel) + 1 + half, vbar[half:], cyan)

    next_idx = st.next_idx() if st.queue else None
    if next_idx is not None and next_idx != st.current_idx:
        next_title = st.queue[next_idx].get("title") or "Unknown"
        S(win, 11, 2, "UP NEXT", dim | curses.A_BOLD)
        S(win, 12, 2, trunc(f"{CHARS['arrow']} {next_title}", iw), white)

    draw_hrule(win, p_h - 5, 0, p_w, accent)

    # Progress bar
    elapsed  = player.get_position()
    duration = player.get_duration()
    if elapsed is not None and duration and duration > 0:
        prog   = min(1.0, elapsed / duration)
        bw     = iw - 2
        filled = round(prog * bw)
        pulse  = st.spin_idx % 6
        bar_chars = []
        for i in range(bw):
            if i < filled:
                bar_chars.append("▓" if i % 6 == pulse else CHARS["bar_fill"])
            else:
                bar_chars.append(CHARS["bar_empty"])
        bar  = "".join(bar_chars)
        tstr = f"{fmt_t(elapsed)}  {CHARS['arrow']}  {fmt_t(duration)}"
        S(win, p_h-4, 2, tstr, dim)
        S(win, p_h-3, 2, bar[:filled], accent | curses.A_BOLD)
        S(win, p_h-3, 2 + filled, bar[filled:], dim)
        S(win, p_h-3, p_w - 5, f"{int(prog*100):3d}%", accent)
    else:
        sp = CHARS["spin"][st.spin_idx % 4]
        S(win, p_h-4, 2, f"{sp}  buffering…", dim | curses.A_DIM)

    status = st.get_status()
    if status:
        S(win, p_h-2, 2, trunc(status, iw), stat | curses.A_DIM)

    win.refresh()


def render_queue_panel(win, st, p_w, p_h):
    win.erase()
    accent = curses.color_pair(C_ACCENT)
    dim    = curses.color_pair(C_DIM)
    cyan   = curses.color_pair(C_CYAN)
    hl     = curses.color_pair(C_QUEUE_H)

    draw_box(win, p_h, p_w, accent)

    visible_indices = st.visible_indices()
    count_label = f"{len(visible_indices)}/{len(st.queue)}" if len(visible_indices) != len(st.queue) else str(len(st.queue))
    mode_bits = []
    if st.shuffle:
        mode_bits.append(f"{CHARS['shuffle_on']} SHUFFLE")
    if st.favorites_only:
        mode_bits.append("♥ FAVS")
    suffix = "  " + "  ".join(mode_bits) if mode_bits else ""

    if st.shuffle or st.favorites_only:
        panel_label(win, f"Q U E U E  ({count_label}){suffix}", p_w, cyan)
    else:
        panel_label(win, f"Q U E U E  ({count_label})", p_w, accent)

    filter_line = ""
    if st.filter_mode:
        filter_line = f"/ {st.filter_text}"
    elif st.filter_text:
        filter_line = f"filter: {st.filter_text}"
    if filter_line:
        S(win, 1, 2, trunc(filter_line, p_w - 4), cyan | curses.A_BOLD)

    visible = p_h - 5
    if st.queue_cursor not in visible_indices and visible_indices:
        st.queue_cursor = visible_indices[0]
    cursor_pos = visible_indices.index(st.queue_cursor) if st.queue_cursor in visible_indices else 0
    if cursor_pos < st.queue_offset:
        st.queue_offset = cursor_pos
    elif cursor_pos >= st.queue_offset + visible:
        st.queue_offset = cursor_pos - visible + 1
    st.queue_offset = max(0, min(st.queue_offset, max(0, len(visible_indices) - visible)))

    for i in range(visible):
        pos = st.queue_offset + i
        if pos >= len(visible_indices):
            break
        idx = visible_indices[pos]
        fav = "♥" if idx in st.favorites else " "
        dur = fmt_t(st.queue[idx].get("duration")) if st.queue[idx].get("duration") else "     "
        label  = trunc(st.queue[idx].get("title") or "Unknown", p_w - 18)
        is_cur = idx == st.current_idx
        is_cursor = idx == st.queue_cursor
        prefix = f"{idx+1:3}. {fav} "
        suffix = f" {dur}"

        if is_cur:
            S(win, i+3, 1, trunc(f" {CHARS['bullet']} {fav} {label}{suffix}", p_w - 2),
              hl | curses.A_BOLD | curses.A_REVERSE)
        elif is_cursor:
            S(win, i+3, 1, trunc(f"{prefix}{label}{suffix}", p_w - 2),
              accent | curses.A_BOLD)
        elif st.shuffle and idx not in st.shuffle_pool and idx != st.current_idx:
            # Already played this shuffle cycle
            S(win, i+3, 1, trunc(f"{prefix}{label}{suffix}", p_w - 2), dim | curses.A_DIM)
        else:
            S(win, i+3, 1, trunc(f"{prefix}{label}{suffix}", p_w - 2), dim)

    total = len(visible_indices)
    if total > visible:
        end = min(st.queue_offset + visible, total)
        note = f" {st.queue_offset+1}-{end}/{total} "
        S(win, p_h-2, p_w-len(note)-1, note, dim | curses.A_DIM)
    elif not visible_indices:
        S(win, p_h//2, max(2, (p_w - 18)//2), "No matching tracks", dim | curses.A_DIM)

    win.refresh()


def render_footer(win, width, st):
    win.erase()
    accent = curses.color_pair(C_ACCENT)
    dim    = curses.color_pair(C_DIM)

    try:
        win.addstr(0, 0, CHARS["h_line"] * (width - 1), accent)
    except curses.error:
        pass

    if st.view == "player":
        keys = [("Q","quit"),("Space","play"),("N","next"),("B","back"),
                ("S","shuffle"),("F","fav"),("T","theme"),
                ("↑↓","vol"),("←→","seek"),("TAB","queue"),("?","help")]
        compact_keys = [("Q","quit"),("Space","play"),("N","next"),
                        ("↑↓","vol"),("TAB","queue"),("?","help")]
    else:
        keys = [("TAB","player"),("↑↓","move"),("↵","play"),("/","filter"),
                ("F","fav"),("A","favs"),("Q","quit"),("?","help")]
        compact_keys = [("TAB","player"),("↑↓","move"),("↵","play"),
                        ("/","filter"),("Q","quit"),("?","help")]

    need = sum(len(k)+len(v)+4 for k,v in keys) + len(keys)
    if need > width - 2:
        keys = compact_keys

    cx = max(0, (width - sum(len(k)+len(v)+4 for k,v in keys) - len(keys)) // 2)
    for i, (k, v) in enumerate(keys):
        S(win, 1, cx, f" {k} ", accent | curses.A_BOLD)
        cx += len(k) + 2
        S(win, 1, cx, f"{CHARS['dot']} {v} ", dim)
        cx += len(v) + 4
        if i < len(keys) - 1:
            S(win, 1, cx, CHARS["v_line"], accent)
            cx += 1

    win.refresh()


def render_header(win, banner, width, st):
    win.erase()
    colors = [C_TITLE, C_CYAN, C_MAGENTA]
    for i, line in enumerate(banner):
        cp = curses.color_pair(colors[i % len(colors)])
        S(win, i, max(0, (width - len(line))//2), line, cp | curses.A_BOLD)
    win.refresh()

# ─── Main ─────────────────────────────────────────────────────────────────────

def run_ui(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    stdscr.nodelay(True)
    stdscr.keypad(True)

    st = State()
    apply_theme(st)

    height, width = stdscr.getmaxyx()
    if height < 24 or width < 82:
        S(stdscr, 0, 0,
          f"  Terminal too small ({width}×{height}). Need 82×24 minimum.  ",
          curses.color_pair(C_STATUS) | curses.A_BOLD)
        stdscr.refresh()
        curses.napms(3000)
        return

    # ── URL Input ───────────────────────────────────────────────────────────
    url = get_url_input(stdscr)
    if not url:
        return

    stdscr.clear()
    stdscr.refresh()

    if height < 30:
        banner = f_title.renderText("MT").splitlines()
    else:
        banner = f_title.renderText("MusicalTerm").splitlines()
    banner_h = len(banner) + 1
    art_h = max(12, min(20, height - banner_h - 5))
    art_w = max(24, min(40, art_h * 2))
    p_w  = max(44, min(width - art_w - 6, 62))
    p_h  = art_h
    sx   = max(0, (width - art_w - p_w - 2) // 2)
    cy   = banner_h + 1

    header_win = curses.newwin(banner_h, width,   0,        0)
    art_win    = curses.newwin(art_h,    art_w,   cy,       sx)
    main_win   = curses.newwin(p_h,      p_w,     cy,       sx + art_w + 2)
    footer_win = curses.newwin(3,        width,   height-3, 0)

    render_header(header_win, banner, width, st)

    S(stdscr, cy + art_h//2, sx + 2, "  ◐  fetching playlist…  ",
      curses.color_pair(C_DIM) | curses.A_DIM)
    stdscr.refresh()

    media = core.extract_media(url)
    if not media or not media.get("tracks"):
        S(stdscr, cy + art_h//2, sx + 2, "  ✕  failed to load media. Check URL and try again.  ",
          curses.color_pair(C_STATUS) | curses.A_BOLD)
        stdscr.refresh()
        curses.napms(3000)
        return

    st.queue = media["tracks"]
    st.media_title = media.get("title") or ""
    st.media_type = media.get("type") or ""
    st.reset_shuffle_pool()

    def start_track(idx, push=True):
        idx = max(0, min(idx, len(st.queue) - 1))
        if push and st.current_idx != idx:
            st.history.append(st.current_idx)
        st.current_idx = idx
        st.queue_cursor = idx
        if idx in st.shuffle_pool:
            st.shuffle_pool.remove(idx)
        track = st.queue[idx]
        player.play_stream(track["url"])
        player.set_volume(st.volume)
        st.paused = False
        trigger_art_load(track["url"], art_w, art_h)
        st.set_status(f"{CHARS['play']}  {trunc(track['title'] or '…', 40)}")

    start_track(0, push=False)
    _end_armed = False

    while True:
        key = stdscr.getch()
        char = chr(key).lower() if 0 <= key < 256 else ""

        if st.help_open:
            if char in ("?", "q") or key == 27:
                st.help_open = False
            render_header(header_win, banner, width, st)
            render_art_panel(art_win, st, art_w, art_h)
            (render_player_panel if st.view == "player" else render_queue_panel)(
                main_win, st, p_w, p_h)
            render_footer(footer_win, width, st)
            render_help_overlay(stdscr, st)
            st.spin_idx += 1
            curses.napms(100)
            continue

        if char == "?":
            st.help_open = True

        elif char == "q":
            player.stop_stream()
            break

        elif key == ord("\t"):
            st.view = "queue" if st.view == "player" else "player"
            if st.view == "queue":
                st.sync_cursor_to_current()

        elif st.view == "queue":
            if st.filter_mode:
                if key in (27,):
                    st.filter_mode = False
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    st.filter_text = st.filter_text[:-1]
                elif key in [ord("\n"), curses.KEY_ENTER]:
                    st.filter_mode = False
                elif char and ord(char) >= 32:
                    st.filter_text += chr(key)
                visible = st.visible_indices()
                if visible:
                    st.queue_cursor = visible[0]
                    st.queue_offset = 0
            elif key == curses.KEY_UP:
                visible = st.visible_indices()
                if visible:
                    pos = visible.index(st.queue_cursor) if st.queue_cursor in visible else 0
                    st.queue_cursor = visible[max(0, pos - 1)]
            elif key == curses.KEY_DOWN:
                visible = st.visible_indices()
                if visible:
                    pos = visible.index(st.queue_cursor) if st.queue_cursor in visible else 0
                    st.queue_cursor = visible[min(len(visible) - 1, pos + 1)]
            elif char == "/":
                st.filter_mode = True
                st.filter_text = ""
            elif char == "a":
                st.favorites_only = not st.favorites_only
                st.queue_offset = 0
                visible = st.visible_indices()
                if visible:
                    st.queue_cursor = visible[0]
                st.set_status("showing favorites" if st.favorites_only else "showing all tracks")
            elif char == "f":
                target = st.queue_cursor
                if target in st.favorites:
                    st.favorites.remove(target)
                    st.set_status("removed favorite")
                else:
                    st.favorites.add(target)
                    st.set_status("added favorite")
            elif key in [ord("\n"), curses.KEY_ENTER]:
                if st.visible_indices():
                    start_track(st.queue_cursor)
                    st.view = "player"

        else:
            if char == "n":
                start_track(st.next_idx())
            elif char == "b":
                if st.history:
                    start_track(st.history.pop(), push=False)
                elif st.current_idx > 0:
                    start_track(st.current_idx - 1)
            elif char in ("p", " "):
                if st.paused:
                    player.resume_stream()
                    st.paused = False
                    st.set_status(f"{CHARS['play']}  resumed")
                else:
                    player.pause_stream()
                    st.paused = True
                    st.set_status(f"{CHARS['pause']}  paused")
            elif char == "r":
                player.resume_stream()
                st.paused = False
                st.set_status(f"{CHARS['play']}  resumed")
            elif char == "s":
                st.shuffle = not st.shuffle
                if st.shuffle:
                    st.reset_shuffle_pool()
                    st.set_status(f"{CHARS['shuffle_on']}  shuffle on  ·  {len(st.shuffle_pool)} tracks in pool")
                else:
                    st.shuffle_pool = []
                    st.set_status(f"{CHARS['shuffle_off']}  shuffle off")
            elif char == "l":
                st.repeat = not st.repeat
                st.set_status(f"{CHARS['repeat_on']}  repeat {'on' if st.repeat else 'off'}")
            elif char == "m":
                st.muted = not st.muted
                player.toggle_mute()
                st.set_status(f"{CHARS['mute']}  {'muted' if st.muted else 'unmuted'}")
            elif char == "f":
                if st.current_idx in st.favorites:
                    st.favorites.remove(st.current_idx)
                    st.set_status("removed favorite")
                else:
                    st.favorites.add(st.current_idx)
                    st.set_status("added favorite")
            elif char == "t":
                st.theme_idx = (st.theme_idx + 1) % len(THEMES)
                apply_theme(st)
                st.set_status(f"theme: {THEMES[st.theme_idx]['name']}")
            elif key == curses.KEY_UP:
                st.volume = min(100, st.volume+5)
                player.set_volume(st.volume)
                st.set_status(f"{CHARS['vol']}  {st.volume}%", 1.5)
            elif key == curses.KEY_DOWN:
                st.volume = max(0, st.volume-5)
                player.set_volume(st.volume)
                st.set_status(f"{CHARS['vol']}  {st.volume}%", 1.5)
            elif key == curses.KEY_RIGHT:
                player.seek(10)
                st.set_status("⏩  +10 s", 1.0)
            elif key == curses.KEY_LEFT:
                player.seek(-10)
                st.set_status("⏪  −10 s", 1.0)

        # Auto-advance
        if not st.paused and player.is_running():
            pos = player.get_position()
            dur = player.get_duration()
            near = pos is not None and dur and dur > 0 and (dur - pos) < 0.8
            if near and not _end_armed:
                _end_armed = True
                start_track(
                    st.current_idx if st.repeat else st.next_idx(),
                    push=not st.repeat
                )
            elif not near:
                _end_armed = False
        elif not player.is_running() and not st.paused and st.queue:
            start_track(st.next_idx())

        # Render
        render_header(header_win, banner, width, st)
        render_art_panel(art_win, st, art_w, art_h)
        (render_player_panel if st.view == "player" else render_queue_panel)(
            main_win, st, p_w, p_h)
        render_footer(footer_win, width, st)
        if st.help_open:
            render_help_overlay(stdscr, st)

        st.spin_idx += 1
        curses.napms(100)


if __name__ == "__main__":
    curses.wrapper(run_ui)
