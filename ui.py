"""
MusicalTerm — Terminal Music Player
Aesthetic: Dark obsidian / warm amber & rose accents
Enhanced with: animated waveform, richer dancer, party mode, EQ bars
"""

import curses
import threading
import random
import time
import os
import tempfile
import math
import re
from pyfiglet import Figlet
import core
import player

# ─── Lyrics Parser ───────────────────────────────────────────────────────────

def parse_lyrics(raw):
    """
    Attempts to parse LRC, SRT, or VTT into a list of (start_time, text).
    """
    if not raw: return []
    
    # 1. Try LRC format: [00:12.34] text
    lrc_pattern = re.compile(r'\[(\d+):(\d+\.?\d*)\](.*)')
    lrc_lines = []
    for line in raw.splitlines():
        match = lrc_pattern.search(line)
        if match:
            m, s, txt = match.groups()
            lrc_lines.append((int(m) * 60 + float(s), txt.strip()))
    if lrc_lines:
        return sorted(lrc_lines, key=lambda x: x[0])

    # 2. Try SRT/VTT format: 00:00:00.000 --> 00:00:02.000
    # simplified: just find timestamps
    time_pattern = re.compile(r'(\d{2}:\d{2}:\d{2}[\.,]\d{3}) --> (\d{2}:\d{2}:\d{2}[\.,]\d{3})')
    lines = []
    parts = re.split(time_pattern, raw)
    # parts[0] is header
    # parts[1] is start, parts[2] is end, parts[3] is text
    for i in range(1, len(parts), 3):
        start_str = parts[i].replace(',', '.')
        # convert HH:MM:SS.mmm to seconds
        h, m, s = start_str.split(':')
        start_time = int(h) * 3600 + int(m) * 60 + float(s)
        
        text = parts[i+2].strip()
        # Clean up tags like <c> or 00:00:00.000
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\d{2}:\d{2}:\d{2}[\.,]\d{3}', '', text)
        text = "\n".join([l for l in text.splitlines() if l.strip() and "-->" not in l])
        
        if text:
            lines.append((start_time, text))
            
    return sorted(lines, key=lambda x: x[0])


# ─── Fonts ────────────────────────────────────────────────────────────────────
try:
    f_title = Figlet(font="slant")
except Exception:
    f_title = Figlet(font="small")

# ─── Design Tokens ────────────────────────────────────────────────────────────
CHARS = {
    "bar_fill": "█",
    "bar_empty": "░",
    "vol_fill": "▰",
    "vol_empty": "▱",
    "h_line": "━",
    "v_line": "┃",
    "tl": "╭",
    "tr": "╮",
    "bl": "╰",
    "br": "╯",
    "t_left": "├",
    "t_right": "┤",
    "play": "▶",
    "pause": "⏸",
    "shuffle_on": "⇄",
    "shuffle_off": "⇒",
    "repeat_on": "↺",
    "repeat_off": "↷",
    "mute": "✕",
    "vol": "♪",
    "dot": "·",
    "arrow": "›",
    "bullet": "◆",
    "dim_bullet": "◇",
    "spin": ["◐", "◓", "◑", "◒"],
    "eq": ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"],
    "heart": "♥",
    "star": "★",
    "note": "♫",
    "wave": "≋",
    "fire": "🔥",  # fallback to * if unsupported
    "crown": "♛",
}

# ─── Color Pair IDs ───────────────────────────────────────────────────────────
C_ACCENT = 1
C_DIM = 2
C_WHITE = 3
C_GREEN = 4
C_TITLE = 5
C_STATUS = 6
C_QUEUE_H = 7
C_ART_BG = 8
C_CYAN = 9
C_MAGENTA = 10
C_ORANGE = 11  # NEW: warm orange for EQ
C_PINK = 12  # NEW: hot pink for party mode
C_GOLD = 13  # NEW: gold for favorites

# ─── EQ Bar Physics ───────────────────────────────────────────────────────────
# Simulated EQ bars that bounce realistically to "music"
EQ_BANDS = 12
eq_heights = [0.0] * EQ_BANDS
eq_targets = [0.0] * EQ_BANDS
eq_vel = [0.0] * EQ_BANDS
_eq_tick = 0


def update_eq(paused=False):
    """Physics-based EQ simulation. Bands have inertia and decay."""
    global eq_heights, eq_targets, eq_vel, _eq_tick
    _eq_tick += 1
    if paused:
        # Decay gracefully when paused
        for i in range(EQ_BANDS):
            eq_heights[i] = max(0.0, eq_heights[i] - 0.08)
        return

    # Generate new random targets every ~8 ticks
    if _eq_tick % 8 == 0:
        for i in range(EQ_BANDS):
            # Low/mid/high frequency shape: more energy in mids
            band_energy = 1.0
            if i < 2 or i > EQ_BANDS - 3:
                band_energy = 0.6  # less at extremes
            elif 3 <= i <= 6:
                band_energy = 1.2  # boost in mids
            eq_targets[i] = random.random() * band_energy

    # Spring physics: height chases target with velocity
    for i in range(EQ_BANDS):
        spring = (eq_targets[i] - eq_heights[i]) * 0.35
        eq_vel[i] = eq_vel[i] * 0.6 + spring
        eq_heights[i] = max(0.0, min(1.0, eq_heights[i] + eq_vel[i]))


# ─── Art Helpers ─────────────────────────────────────────────────────────────


def to256(r, g, b):
    if abs(r - g) < 4 and abs(g - b) < 4:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + (r - 8) // 10

    def q(x):
        if x < 48:
            return 0
        if x < 115:
            return 1
        if x < 155:
            return 2
        if x < 195:
            return 3
        if x < 235:
            return 4
        return 5

    return 16 + q(r) * 36 + q(g) * 6 + q(b)


# ─── Art State ────────────────────────────────────────────────────────────────
art_lock = threading.Lock()
art_data = {
    "pixels": None,
    "w": 0,
    "h": 0,
    "loading": False,
    "dom_idx": 214,
    "pairs": {},
    "nxt_pair": 200,
}


def get_art_pair(fg, bg):
    global art_data
    key = (fg, bg)
    if key in art_data["pairs"]:
        return art_data["pairs"][key]

    pair_id = art_data["nxt_pair"]
    # Curses usually supports 256 color pairs by default, but can be more.
    # We limit to 255 to be safe if COLOR_PAIRS is small.
    if pair_id >= getattr(curses, "COLOR_PAIRS", 256) - 1:
        # Recycle pairs if we run out? For now just fallback.
        return 0

    try:
        curses.init_pair(pair_id, fg, bg)
        art_data["pairs"][key] = pair_id
        art_data["nxt_pair"] += 1
        return pair_id
    except Exception:
        return 0


# ─── State ────────────────────────────────────────────────────────────────────
class State:
    def __init__(self):
        self.queue = []
        self.shuffle_pool = []
        self.history = []
        self.current_idx = 0
        self.queue_cursor = 0
        self.volume = 70
        self.paused = False
        self.repeat = False
        self.shuffle = False
        self.muted = False
        self.view = "player"
        self.art_mode = "art"  # art, dancer, lyrics
        self.queue_offset = 0
        self.filter_text = ""
        self.filter_mode = False
        self.favorites = set()
        self.favorites_only = False
        self.help_open = False
        self.theme_idx = 0
        self.media_title = ""
        self.media_type = ""
        self._status_msg = ""
        self._status_ts = 0
        self.spin_idx = 0
        self.party_mode = False  # NEW: rainbow / party mode
        self.show_eq = True  # NEW: show EQ bars in art panel
        self.track_count = 0  # NEW: how many tracks played this session
        self.lyrics = []
        self.current_lyric_idx = -1

    def set_status(self, msg, ttl=3.0):
        self._status_msg = msg
        self._status_ts = time.time() + ttl

    def get_status(self):
        return self._status_msg if time.time() < self._status_ts else ""

    def reset_shuffle_pool(self):
        self.shuffle_pool = [i for i in range(len(self.queue)) if i != self.current_idx]
        random.shuffle(self.shuffle_pool)

    def next_idx(self):
        if not self.queue:
            return 0
        if self.shuffle:
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


# ─── Dancer Frames ────────────────────────────────────────────────────────────
# Much more expressive multi-line dancer with wider animations
DANCER_FRAMES = [
    # Frame 0: Neutral pose
    [
        "   \\o/  ",
        "    |   ",
        "   / \\  ",
    ],
    # Frame 1: Left dip
    [
        "  \\o    ",
        "   |\\   ",
        "  /  \\  ",
    ],
    # Frame 2: Right arm up
    [
        "    o/  ",
        "   /|   ",
        "  / \\   ",
    ],
    # Frame 3: Jump / both arms up
    [
        "  \\o/   ",
        "   |    ",
        "  _^_   ",
    ],
    # Frame 4: Spin left
    [
        "   o\\   ",
        "  /|    ",
        "  / \\   ",
    ],
    # Frame 5: Waving
    [
        "  \\o/   ",
        "   |\\_  ",
        "   |\\   ",
    ],
    # Frame 6: Squat / groove low
    [
        "  \\o/   ",
        "  -|-   ",
        "  > <   ",
    ],
    # Frame 7: Point up
    [
        "   ô    ",
        "  /|/   ",
        "  / \\   ",
    ],
    # Frame 8: Breakdance lean
    [
        "    o   ",
        "  --|   ",
        "    /\\ ",
    ],
]

# Sequence that looks like actual dancing: grove rhythmically
DANCE_SEQUENCE = [0, 1, 0, 2, 0, 3, 0, 2, 0, 1, 6, 1, 6, 5, 0, 7, 0, 4, 0, 8]

# Musical notes and effects that float around the dancer
FLOATERS = ["♪", "♫", "♩", "♬", "~", "*", "·", "°"]
PARTY_FLOATERS = ["★", "✦", "◈", "◉", "❋", "✿", "◆", "▲"]

# ─── Art Loading ──────────────────────────────────────────────────────────────


def _bg_load_art(url, art_w, art_h, st):
    global art_data
    with art_lock:
        art_data["loading"] = True

    cover_path = os.path.join(
        tempfile.gettempdir(), f"musicalterm_cover_{os.getpid()}.jpg"
    )
    
    # Reset lyrics
    st.lyrics = []
    st.current_lyric_idx = -1
    
    # Fetch lyrics in background
    raw_lyrics = core.fetch_lyrics(url)
    if raw_lyrics:
        st.lyrics = parse_lyrics(raw_lyrics)

    if core.download_thumbnail(url, cover_path):
        px, w, h, dom_rgb = core.get_album_art_matrix(
            cover_path, max_w=art_w - 4, max_h=art_h - 4
        )
        if px:
            indices = [to256(r, g, b) for r, g, b in px]
            dom_idx = to256(*dom_rgb)
            with art_lock:
                art_data.update(pixels=indices, w=w, h=h, dom_idx=dom_idx)
                art_data["pairs"] = {}
                art_data["nxt_pair"] = 200

    with art_lock:
        art_data["loading"] = False


def trigger_art_load(url, art_w, art_h, st):
    threading.Thread(target=_bg_load_art, args=(url, art_w, art_h, st), daemon=True).start()


def draw_album_art(win, st, art_w, art_h):
    win_h, win_w = win.getmaxyx()
    with art_lock:
        pixels = art_data.get("pixels")
        w = art_data.get("w", 0)
        h = art_data.get("h", 0)

    if not pixels or w == 0 or h == 0:
        draw_dancer(win, st)
        return

    # Center the image
    start_y = max(1, (win_h - (h // 2)) // 2)
    start_x = max(1, (win_w - w) // 2)

    # Use half-blocks to render
    # Each row in terminal is 2 pixels high in the image
    for y in range(0, h - 1, 2):
        ry = start_y + (y // 2)
        if ry >= win_h - 1:
            break
        for x in range(w):
            rx = start_x + x
            if rx >= win_w - 1:
                break
            
            top_color = pixels[y * w + x]
            bot_color = pixels[(y + 1) * w + x]
            
            pair = get_art_pair(top_color, bot_color)
            S(win, ry, rx, "▀", curses.color_pair(pair))


def draw_lyrics(win, st, art_w, art_h):
    """
    Draws the synced lyrics.
    """
    win_h, win_w = win.getmaxyx()
    if not st.lyrics:
        S(win, win_h // 2, max(1, (art_w - 18) // 2), " No lyrics found. ", curses.color_pair(C_DIM))
        return

    pos = player.get_position() or 0
    # Find current lyric
    idx = -1
    for i, (ts, text) in enumerate(st.lyrics):
        if ts <= pos:
            idx = i
        else:
            break
    
    st.current_lyric_idx = idx
    
    accent = curses.color_pair(C_ACCENT)
    white = curses.color_pair(C_WHITE)
    dim = curses.color_pair(C_DIM)
    
    visible_lines = win_h - 4
    start_y = 2
    
    # Show a few lines before and after
    offset = max(0, idx - (visible_lines // 2))
    for i in range(visible_lines):
        curr = offset + i
        if curr >= len(st.lyrics):
            break
        
        ts, text = st.lyrics[curr]
        ry = start_y + i
        attr = white | curses.A_BOLD if curr == idx else dim
        if curr == idx:
            # Highlight current line
            S(win, ry, 2, f"{CHARS['arrow']} ", accent)
            S(win, ry, 4, trunc(text, art_w - 6), attr)
        else:
            S(win, ry, 4, trunc(text, art_w - 6), attr)


def draw_dancer(win, st):
    """
    Draws the animated dancer with floating music notes, EQ bars, and party effects.
    """
    win_h, win_w = win.getmaxyx()

    with art_lock:
        dom_idx = art_data.get("dom_idx", 214)

    try:
        curses.init_pair(C_ART_BG, dom_idx, -1)
    except Exception:
        pass

    accent = curses.color_pair(C_ART_BG)
    dim = curses.color_pair(C_DIM)
    white = curses.color_pair(C_WHITE)
    cyan = curses.color_pair(C_CYAN)
    mag = curses.color_pair(C_MAGENTA)
    green = curses.color_pair(C_GREEN)

    # Party mode: cycle through colors
    if st.party_mode:
        party_colors = [
            C_ACCENT,
            C_CYAN,
            C_MAGENTA,
            C_GREEN,
            C_STATUS,
            C_ORANGE,
            C_PINK,
        ]
        accent = curses.color_pair(party_colors[st.spin_idx % len(party_colors)])

    # Pick frame from dance sequence
    seq_pos = (st.spin_idx // 3) % len(DANCE_SEQUENCE)
    frame_idx = DANCE_SEQUENCE[seq_pos]
    frame = DANCER_FRAMES[frame_idx]

    fh = len(frame)
    fw = max(len(line) for line in frame)

    cy = win_h // 2
    cx = win_w // 2

    # ── Stage floor ──
    floor_y = cy + fh
    if floor_y < win_h - 1:
        floor_str = "─" * min(fw + 6, win_w - 4)
        S(win, floor_y, max(1, cx - len(floor_str) // 2), floor_str, dim)

    # ── Shadow (one row below dancer) ──
    shadow_str = "░" * (fw - 2)
    shadow_y = floor_y
    if shadow_y < win_h - 1:
        S(
            win,
            shadow_y,
            max(1, cx - len(shadow_str) // 2),
            shadow_str,
            dim | curses.A_DIM,
        )

    # ── Dancer body ──
    start_y = cy - fh // 2
    start_x = cx - fw // 2

    for i, line in enumerate(frame):
        ry = start_y + i
        rx = start_x
        if ry < 1 or ry >= win_h - 1:
            continue
        # Head gets accent+bold, body gets white, legs get dim
        if i == 0:
            attr = accent | curses.A_BOLD
        elif i == 1:
            attr = white
        else:
            attr = dim | curses.A_BOLD
        # In party mode the whole dancer cycles colors
        if st.party_mode:
            attr = (
                curses.color_pair(party_colors[(st.spin_idx + i) % len(party_colors)])
                | curses.A_BOLD
            )
        S(win, ry, rx, line, attr)

    # ── Floating musical notes ──
    # Use deterministic positions based on spin_idx so they move smoothly
    floater_list = PARTY_FLOATERS if st.party_mode else FLOATERS
    num_floaters = 5 if st.party_mode else 4
    for j in range(num_floaters):
        # Each floater has its own phase
        phase = st.spin_idx * 0.15 + j * 1.8
        fx = int(cx + math.sin(phase) * (win_w // 3 - 2))
        fy = int(cy + math.cos(phase * 0.7 + j) * (win_h // 3))
        fy -= (st.spin_idx // 4 + j * 3) % (win_h - 3) - (win_h // 4)  # upward drift

        if 1 <= fy < win_h - 1 and 1 <= fx < win_w - 1:
            glyph = floater_list[j % len(floater_list)]
            if st.party_mode:
                col = curses.color_pair(
                    party_colors[(j + st.spin_idx // 2) % len(party_colors)]
                )
            else:
                col = accent if j % 2 == 0 else dim
            S(win, fy, fx, glyph, col | curses.A_DIM)

    # ── EQ bars at bottom ──
    if st.show_eq and not st.paused:
        eq_y = win_h - 3
        eq_x = max(1, cx - EQ_BANDS // 2)
        eq_max_h = min(4, win_h - 4)

        for b in range(EQ_BANDS):
            bx = eq_x + b
            if bx >= win_w - 1:
                break
            h_val = int(eq_heights[b] * eq_max_h)
            for row in range(h_val):
                ey = eq_y - row
                if ey < 1:
                    break
                # Color gradient: green at bottom, amber in mid, red at top
                if row == 0:
                    col = green
                elif row == 1:
                    col = accent
                else:
                    col = curses.color_pair(C_STATUS)
                if st.party_mode:
                    col = curses.color_pair(party_colors[(b + row) % len(party_colors)])
                S(win, ey, bx, CHARS["eq"][min(row * 2, 7)], col | curses.A_BOLD)

    # ── Pulsing ring around dancer when track starts ──
    if st.spin_idx < 20 and not st.paused:
        r = min(win_w // 3, win_h // 2) - 1
        for angle in range(0, 360, 20):
            rad = math.radians(angle)
            ry = int(cy + r * 0.5 * math.sin(rad))
            rx = int(cx + r * math.cos(rad))
            if 1 <= ry < win_h - 1 and 1 <= rx < win_w - 1:
                alpha = max(0, 1.0 - st.spin_idx / 20.0)
                glyph = "·" if alpha < 0.5 else "○"
                S(win, ry, rx, glyph, accent | curses.A_DIM)


# ─── Primitives ───────────────────────────────────────────────────────────────


def S(win, y, x, text, attr=0):
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


def draw_box(win, h, w, cp):
    c = CHARS
    S(win, 0, 0, c["tl"] + c["h_line"] * (w - 2) + c["tr"], cp)
    S(win, h - 1, 0, c["bl"] + c["h_line"] * (w - 2) + c["br"], cp)
    for r in range(1, h - 1):
        S(win, r, 0, c["v_line"], cp)
        S(win, r, w - 1, c["v_line"], cp)


def draw_hrule(win, y, x, w, cp):
    S(win, y, x, CHARS["t_left"], cp)
    S(win, y, x + 1, CHARS["h_line"] * (w - 2), cp)
    S(win, y, x + w - 1, CHARS["t_right"], cp)


def panel_label(win, text, w, cp):
    label = f"  {text}  "
    S(win, 0, max(2, (w - len(label)) // 2), label, cp | curses.A_BOLD)


def trunc(s, n):
    return (s[: n - 1] + "…") if len(s) > n else s


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


# ─── Themes ───────────────────────────────────────────────────────────────────
THEMES = [
    {
        "name": "ember",
        "accent": 214,  # warm amber
        "dim": 238,
        "white": 255,
        "green": 150,
        "title": 214,
        "status": 203,
        "queue": 214,
        "art": 94,
        "cyan": 216,
        "magenta": 183,
        "orange": 208,
        "pink": 205,
        "gold": 220,
    },
    {
        "name": "neon",
        "accent": 81,  # electric cyan
        "dim": 244,
        "white": 255,
        "green": 118,
        "title": 45,
        "status": 203,
        "queue": 81,
        "art": 33,
        "cyan": 159,
        "magenta": 213,
        "orange": 208,
        "pink": 198,
        "gold": 226,
    },
    {
        "name": "rose",
        "accent": 211,  # soft rose
        "dim": 239,
        "white": 255,
        "green": 156,
        "title": 213,
        "status": 196,
        "queue": 211,
        "art": 161,
        "cyan": 219,
        "magenta": 177,
        "orange": 215,
        "pink": 200,
        "gold": 221,
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
        "orange": 252,
        "pink": 246,
        "gold": 255,
    },
    {
        "name": "matrix",
        "accent": 46,  # pure green
        "dim": 22,
        "white": 82,
        "green": 118,
        "title": 46,
        "status": 226,
        "queue": 46,
        "art": 28,
        "cyan": 122,
        "magenta": 82,
        "orange": 148,
        "pink": 154,
        "gold": 190,
    },
]


def apply_theme(st):
    theme = THEMES[st.theme_idx % len(THEMES)]
    curses.init_pair(C_ACCENT, theme["accent"], -1)
    curses.init_pair(C_DIM, theme["dim"], -1)
    curses.init_pair(C_WHITE, theme["white"], -1)
    curses.init_pair(C_GREEN, theme["green"], -1)
    curses.init_pair(C_TITLE, theme["title"], -1)
    curses.init_pair(C_STATUS, theme["status"], -1)
    curses.init_pair(C_QUEUE_H, theme["queue"], -1)
    curses.init_pair(C_ART_BG, theme["art"], -1)
    curses.init_pair(C_CYAN, theme["cyan"], -1)
    curses.init_pair(C_MAGENTA, theme["magenta"], -1)
    curses.init_pair(C_ORANGE, theme["orange"], -1)
    curses.init_pair(C_PINK, theme["pink"], -1)
    curses.init_pair(C_GOLD, theme["gold"], -1)


# ─── Help Overlay ─────────────────────────────────────────────────────────────


def render_help_overlay(stdscr, st):
    h, w = stdscr.getmaxyx()
    box_w = min(74, w - 4)
    box_h = min(22, h - 4)
    y = max(1, (h - box_h) // 2)
    x = max(1, (w - box_w) // 2)
    win = curses.newwin(box_h, box_w, y, x)
    accent = curses.color_pair(C_ACCENT)
    dim = curses.color_pair(C_DIM)
    white = curses.color_pair(C_WHITE)
    stat = curses.color_pair(C_STATUS)
    gold = curses.color_pair(C_GOLD)

    win.erase()
    draw_box(win, box_h, box_w, accent)
    panel_label(win, "K E Y S", box_w, accent)

    rows = [
        ("Space / P", "play / pause"),
        ("N / B", "next / previous"),
        ("S", "toggle shuffle"),
        ("L", "toggle loop"),
        ("M", "mute / unmute"),
        ("F", "favorite track"),
        ("A", "show all / favorites only"),
        ("V", f"cycle view (art/dance/lyrics)"),
        ("E", "toggle EQ bars"),
        ("Z", "party mode  ★"),
        ("T", f"next theme  (current: {THEMES[st.theme_idx % len(THEMES)]['name']})"),
        ("Up / Down", "volume ↑↓"),
        ("Left / Right", "seek −10s / +10s"),
        ("Tab", "player / queue view"),
        ("/", "filter queue"),
        ("?", "close help"),
        ("Q", "quit"),
    ]
    col_w = max(20, (box_w - 6) // 2)
    for i, (key, label) in enumerate(rows[: box_h - 4]):
        row = 2 + i
        S(win, row, 3, trunc(key, col_w - 2), gold | curses.A_BOLD)
        S(win, row, col_w, trunc(label, box_w - col_w - 3), dim)

    S(
        win,
        box_h - 2,
        3,
        trunc(f"♪ {st.track_count} tracks played this session", box_w - 5),
        stat | curses.A_DIM,
    )
    win.refresh()


# ─── URL Input Screen ─────────────────────────────────────────────────────────


def get_url_input(stdscr):
    curses.curs_set(1)
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    gold = curses.color_pair(C_ACCENT)
    dim = curses.color_pair(C_DIM)
    white = curses.color_pair(C_WHITE)
    stat = curses.color_pair(C_STATUS)
    cyan = curses.color_pair(C_CYAN)

    banner = f_title.renderText("MT").splitlines()
    for i, line in enumerate(banner):
        S(stdscr, i, max(0, (width - len(line)) // 2), line, gold | curses.A_BOLD)

    cy = len(banner) + 2
    title_line = "  ♪  Paste a YouTube URL or type a search  ♪  "
    S(
        stdscr,
        cy,
        max(0, (width - len(title_line)) // 2),
        title_line,
        white | curses.A_BOLD,
    )
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
        S(stdscr, cy, max(0, (width - 56) // 2), line, dim)
        cy += 1

    cy += 1
    box_w = min(72, width - 6)
    box_x = max(0, (width - box_w) // 2)
    prompt = " Play › "

    S(
        stdscr,
        cy,
        box_x,
        CHARS["tl"] + CHARS["h_line"] * (box_w - 2) + CHARS["tr"],
        gold,
    )
    S(stdscr, cy + 1, box_x, CHARS["v_line"], gold)
    S(stdscr, cy + 1, box_x + box_w - 1, CHARS["v_line"], gold)
    S(
        stdscr,
        cy + 2,
        box_x,
        CHARS["bl"] + CHARS["h_line"] * (box_w - 2) + CHARS["br"],
        gold,
    )
    S(stdscr, cy + 1, box_x + 1, prompt, gold | curses.A_BOLD)
    stdscr.refresh()

    buf = ""
    input_x = box_x + 1 + len(prompt)
    input_w = box_w - 2 - len(prompt)
    err_y = cy + 4

    while True:
        display = buf[-(input_w - 1) :] if len(buf) >= input_w else buf
        S(stdscr, cy + 1, input_x, " " * input_w, 0)
        S(stdscr, cy + 1, input_x, display, white)
        stdscr.move(cy + 1, input_x + min(len(buf), input_w - 1))
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
                S(stdscr, err_y, box_x, " Please enter a URL or search first. ", stat)
                stdscr.refresh()
            elif ch == "\x1b":
                curses.curs_set(0)
                return None
            elif ch == "\x03":
                curses.curs_set(0)
                return None
            elif ch in ("\x08", "\x7f"):
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


# ─── Art Panel ────────────────────────────────────────────────────────────────


def render_art_panel(win, st, art_w, art_h):
    win.erase()

    with art_lock:
        dom_idx = art_data.get("dom_idx", 214)

    try:
        curses.init_pair(C_ART_BG, dom_idx, -1)
        curses.init_pair(C_QUEUE_H, dom_idx, -1)
    except Exception:
        pass

    border_color = curses.color_pair(C_ART_BG)
    dim = curses.color_pair(C_DIM)
    accent = curses.color_pair(C_ACCENT)

    # Party mode: border cycles
    if st.party_mode:
        party_colors = [
            C_ACCENT,
            C_CYAN,
            C_MAGENTA,
            C_GREEN,
            C_STATUS,
            C_ORANGE,
            C_PINK,
        ]
        border_color = curses.color_pair(party_colors[st.spin_idx % len(party_colors)])

    draw_box(win, art_h, art_w, border_color)
    
    mode_labels = {
        "art": "A L B U M",
        "dancer": "D A N C E R",
        "lyrics": "L Y R I C S"
    }
    panel_label(win, mode_labels.get(st.art_mode, "A L B U M"), art_w, border_color)

    # Party mode label
    if st.party_mode:
        S(win, 0, 2, "★ PARTY", curses.color_pair(C_GOLD) | curses.A_BOLD)

    with art_lock:
        loading = art_data["loading"]

    if loading:
        sp = CHARS["spin"][st.spin_idx % 4]
        S(win, art_h // 2, max(1, (art_w - 12) // 2), f" {sp}  loading… ", dim)
        if st.art_mode == "lyrics":
            draw_lyrics(win, st, art_w, art_h)
        elif st.art_mode == "art":
            draw_album_art(win, st, art_w, art_h)
        else:
            draw_dancer(win, st)
    else:
        if st.art_mode == "lyrics":
            draw_lyrics(win, st, art_w, art_h)
        elif st.art_mode == "art":
            draw_album_art(win, st, art_w, art_h)
        else:
            draw_dancer(win, st)

    # EQ mode label
    if st.show_eq and not st.paused and st.art_mode != "lyrics":
        eq_label = "EQ ▂▃▅▄▂"
        S(
            win,
            art_h - 2,
            max(1, (art_w - len(eq_label)) // 2),
            eq_label,
            dim | curses.A_DIM,
        )

    win.refresh()


# ─── Player Panel ─────────────────────────────────────────────────────────────


def render_player_panel(win, st, p_w, p_h):
    win.erase()
    accent = curses.color_pair(C_ACCENT)
    dim = curses.color_pair(C_DIM)
    white = curses.color_pair(C_WHITE)
    grn = curses.color_pair(C_GREEN)
    stat = curses.color_pair(C_STATUS)
    cyan = curses.color_pair(C_CYAN)
    mag = curses.color_pair(C_MAGENTA)
    gold = curses.color_pair(C_GOLD)
    iw = p_w - 4

    draw_box(win, p_h, p_w, accent)
    panel_label(win, "N O W  P L A Y I N G", p_w, accent)

    track = st.queue[st.current_idx] if st.queue else None
    title = track["title"] if track else "No track loaded"
    artist = track.get("uploader") if track else None
    counter = f"{st.current_idx + 1:02}/{len(st.queue):02}"
    is_fav = st.current_idx in st.favorites
    fav_str = f"{CHARS['heart']} " if is_fav else ""
    display_title = f"{fav_str}❖ {trunc(title, iw - len(counter) - len(fav_str) - 6)}"

    title_attr = gold | curses.A_BOLD if is_fav else accent | curses.A_BOLD
    S(win, 2, 2, display_title, title_attr)
    S(win, 2, p_w - len(counter) - 2, counter, dim)

    draw_hrule(win, 3, 0, p_w, accent)

    # ── Status flags row ──
    cx = 2
    if st.paused:
        seg = f"{CHARS['pause']} PAUSED  "
        S(win, 4, cx, seg, stat | curses.A_BOLD)
    else:
        seg = f"{CHARS['play']} PLAYING  "
        S(win, 4, cx, seg, white | curses.A_BOLD)
    cx += len(seg)

    shuf_icon = CHARS["shuffle_on"] if st.shuffle else CHARS["shuffle_off"]
    shuf_attr = cyan | curses.A_BOLD if st.shuffle else dim
    shuf_seg = f"{shuf_icon} SHUFFLE  "
    S(win, 4, cx, shuf_seg, shuf_attr)
    cx += len(shuf_seg)

    rep_icon = CHARS["repeat_on"] if st.repeat else CHARS["repeat_off"]
    rep_attr = mag | curses.A_BOLD if st.repeat else dim
    rep_seg = f"{rep_icon} LOOP  "
    S(win, 4, cx, rep_seg, rep_attr)
    cx += len(rep_seg)

    if st.muted:
        S(win, 4, cx, f"{CHARS['mute']} MUTED  ", stat | curses.A_BOLD)

    if st.party_mode:
        S(win, 4, p_w - 10, "★ PARTY", curses.color_pair(C_GOLD) | curses.A_BOLD)

    if st.shuffle and st.queue:
        remaining = len(st.shuffle_pool)
        total = len(st.queue)
        shuf_info = f"[{remaining}/{total}]"
        S(win, 4, p_w - len(shuf_info) - 2, shuf_info, cyan | curses.A_DIM)

    draw_hrule(win, 5, 0, p_w, accent)

    # ── Meta ──
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
        stats.append(f"{len(st.favorites)} {CHARS['heart']}")
    if st.track_count:
        stats.append(f"#{st.track_count} played")
    if stats:
        S(win, meta_y + 1, 2, trunc("  ·  ".join(stats), iw), cyan | curses.A_DIM)

    # ── Volume bar ──
    vbw = iw - 10
    vfill = round((st.volume / 100) * vbw)
    vbar = CHARS["vol_fill"] * vfill + CHARS["vol_empty"] * (vbw - vfill)
    vlabel = f"{CHARS['vol']} {st.volume:3d}%"
    S(win, 9, 2, vlabel, accent | curses.A_BOLD)
    half = max(0, vbw // 2)
    S(win, 9, 2 + len(vlabel) + 1, vbar[:half], grn)
    S(win, 9, 2 + len(vlabel) + 1 + half, vbar[half:], cyan)

    # ── Up Next ──
    next_idx = st.next_idx() if st.queue else None
    if next_idx is not None and next_idx != st.current_idx:
        next_title = st.queue[next_idx].get("title") or "Unknown"
        next_is_fav = next_idx in st.favorites
        next_prefix = f"{CHARS['heart']} " if next_is_fav else ""
        S(win, 11, 2, "UP NEXT", dim | curses.A_BOLD)
        S(win, 12, 2, trunc(f"{CHARS['arrow']} {next_prefix}{next_title}", iw), white)

    draw_hrule(win, p_h - 5, 0, p_w, accent)

    # ── Progress bar with waveform-style fill ──
    elapsed = player.get_position()
    duration = player.get_duration()
    if elapsed is not None and duration and duration > 0:
        prog = min(1.0, elapsed / duration)
        bw = iw - 2
        filled = round(prog * bw)
        pulse = st.spin_idx % 6
        bar_chars = []
        for i in range(bw):
            if i < filled:
                # Waveform look: vary the fill char slightly
                beat = (i + st.spin_idx) % 8
                bar_chars.append("▓" if beat < 2 else CHARS["bar_fill"])
            else:
                bar_chars.append(CHARS["bar_empty"])
        bar = "".join(bar_chars)
        tstr = f"{fmt_t(elapsed)}  {CHARS['arrow']}  {fmt_t(duration)}"
        S(win, p_h - 4, 2, tstr, dim)
        S(win, p_h - 3, 2, bar[:filled], accent | curses.A_BOLD)
        S(win, p_h - 3, 2 + filled, bar[filled:], dim)
        S(win, p_h - 3, p_w - 5, f"{int(prog * 100):3d}%", accent)
    else:
        sp = CHARS["spin"][st.spin_idx % 4]
        S(win, p_h - 4, 2, f"{sp}  buffering…", dim | curses.A_DIM)

    status = st.get_status()
    if status:
        S(win, p_h - 2, 2, trunc(status, iw), stat | curses.A_DIM)

    win.refresh()


# ─── Queue Panel ──────────────────────────────────────────────────────────────


def render_queue_panel(win, st, p_w, p_h):
    win.erase()
    accent = curses.color_pair(C_ACCENT)
    dim = curses.color_pair(C_DIM)
    cyan = curses.color_pair(C_CYAN)
    hl = curses.color_pair(C_QUEUE_H)
    gold = curses.color_pair(C_GOLD)

    draw_box(win, p_h, p_w, accent)

    visible_indices = st.visible_indices()
    count_label = (
        f"{len(visible_indices)}/{len(st.queue)}"
        if len(visible_indices) != len(st.queue)
        else str(len(st.queue))
    )
    mode_bits = []
    if st.shuffle:
        mode_bits.append(f"{CHARS['shuffle_on']} SHUFFLE")
    if st.favorites_only:
        mode_bits.append(f"{CHARS['heart']} FAVS")
    suffix = "  " + "  ".join(mode_bits) if mode_bits else ""

    if st.shuffle or st.favorites_only:
        panel_label(win, f"Q U E U E  ({count_label}){suffix}", p_w, cyan)
    else:
        panel_label(win, f"Q U E U E  ({count_label})", p_w, accent)

    filter_line = ""
    if st.filter_mode:
        filter_line = f"/ {st.filter_text}▌"
    elif st.filter_text:
        filter_line = f"filter: {st.filter_text}"
    if filter_line:
        S(win, 1, 2, trunc(filter_line, p_w - 4), cyan | curses.A_BOLD)

    visible = p_h - 5
    if st.queue_cursor not in visible_indices and visible_indices:
        st.queue_cursor = visible_indices[0]
    cursor_pos = (
        visible_indices.index(st.queue_cursor)
        if st.queue_cursor in visible_indices
        else 0
    )
    if cursor_pos < st.queue_offset:
        st.queue_offset = cursor_pos
    elif cursor_pos >= st.queue_offset + visible:
        st.queue_offset = cursor_pos - visible + 1
    st.queue_offset = max(
        0, min(st.queue_offset, max(0, len(visible_indices) - visible))
    )

    for i in range(visible):
        pos = st.queue_offset + i
        if pos >= len(visible_indices):
            break
        idx = visible_indices[pos]
        is_fav = idx in st.favorites
        fav = CHARS["heart"] if is_fav else " "
        dur = (
            fmt_t(st.queue[idx].get("duration"))
            if st.queue[idx].get("duration")
            else "     "
        )
        label = trunc(st.queue[idx].get("title") or "Unknown", p_w - 18)
        is_cur = idx == st.current_idx
        is_cursor = idx == st.queue_cursor
        prefix = f"{idx + 1:3}. {fav} "
        suffix_s = f" {dur}"

        if is_cur:
            S(
                win,
                i + 3,
                1,
                trunc(f" {CHARS['bullet']} {fav} {label}{suffix_s}", p_w - 2),
                hl | curses.A_BOLD | curses.A_REVERSE,
            )
        elif is_cursor:
            S(
                win,
                i + 3,
                1,
                trunc(f"{prefix}{label}{suffix_s}", p_w - 2),
                accent | curses.A_BOLD,
            )
        elif is_fav:
            S(
                win,
                i + 3,
                1,
                trunc(f"{prefix}{label}{suffix_s}", p_w - 2),
                gold | curses.A_DIM,
            )
        elif st.shuffle and idx not in st.shuffle_pool and idx != st.current_idx:
            S(
                win,
                i + 3,
                1,
                trunc(f"{prefix}{label}{suffix_s}", p_w - 2),
                dim | curses.A_DIM,
            )
        else:
            S(win, i + 3, 1, trunc(f"{prefix}{label}{suffix_s}", p_w - 2), dim)

    total = len(visible_indices)
    if total > visible:
        end = min(st.queue_offset + visible, total)
        note = f" {st.queue_offset + 1}-{end}/{total} "
        S(win, p_h - 2, p_w - len(note) - 1, note, dim | curses.A_DIM)
    elif not visible_indices:
        S(
            win,
            p_h // 2,
            max(2, (p_w - 18) // 2),
            "No matching tracks",
            dim | curses.A_DIM,
        )

    win.refresh()


# ─── Footer ───────────────────────────────────────────────────────────────────


def render_footer(win, width, st):
    win.erase()
    accent = curses.color_pair(C_ACCENT)
    dim = curses.color_pair(C_DIM)
    gold = curses.color_pair(C_GOLD)

    try:
        win.addstr(0, 0, CHARS["h_line"] * (width - 1), accent)
    except curses.error:
        pass

    if st.view == "player":
        keys = [
            ("Q", "quit"),
            ("Space", "play"),
            ("N", "next"),
            ("V", "view"),
            ("S", "shuffle"),
            ("Z", "party"),
            ("T", "theme"),
            ("↑↓", "vol"),
            ("←→", "seek"),
            ("TAB", "queue"),
            ("?", "help"),
        ]
        compact_keys = [
            ("Q", "quit"),
            ("Space", "play"),
            ("V", "view"),
            ("Z", "party"),
            ("TAB", "queue"),
            ("?", "help"),
        ]
    else:
        keys = [
            ("TAB", "player"),
            ("↑↓", "move"),
            ("↵", "play"),
            ("/", "filter"),
            ("F", "fav"),
            ("A", "favs"),
            ("Q", "quit"),
            ("?", "help"),
        ]
        compact_keys = [
            ("TAB", "player"),
            ("↑↓", "move"),
            ("↵", "play"),
            ("/", "filter"),
            ("Q", "quit"),
            ("?", "help"),
        ]

    need = sum(len(k) + len(v) + 4 for k, v in keys) + len(keys)
    if need > width - 2:
        keys = compact_keys

    cx = max(0, (width - sum(len(k) + len(v) + 4 for k, v in keys) - len(keys)) // 2)
    for i, (k, v) in enumerate(keys):
        key_attr = (
            gold | curses.A_BOLD
            if k == "Z" and st.party_mode
            else accent | curses.A_BOLD
        )
        S(win, 1, cx, f" {k} ", key_attr)
        cx += len(k) + 2
        S(win, 1, cx, f"{CHARS['dot']} {v} ", dim)
        cx += len(v) + 4
        if i < len(keys) - 1:
            S(win, 1, cx, CHARS["v_line"], accent)
            cx += 1

    win.refresh()


# ─── Header ───────────────────────────────────────────────────────────────────


def render_header(win, banner, width, st):
    win.erase()
    # In party mode, cycle colors across banner lines
    if st.party_mode:
        party_colors = [C_ACCENT, C_CYAN, C_MAGENTA, C_GREEN, C_ORANGE, C_PINK]
        for i, line in enumerate(banner):
            cp = curses.color_pair(
                party_colors[(i + st.spin_idx // 5) % len(party_colors)]
            )
            S(win, i, max(0, (width - len(line)) // 2), line, cp | curses.A_BOLD)
    else:
        colors = [C_TITLE, C_CYAN, C_MAGENTA]
        for i, line in enumerate(banner):
            cp = curses.color_pair(colors[i % len(colors)])
            S(win, i, max(0, (width - len(line)) // 2), line, cp | curses.A_BOLD)
    win.refresh()


# ─── Main Loop ────────────────────────────────────────────────────────────────


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
        S(
            stdscr,
            0,
            0,
            f"  Terminal too small ({width}×{height}). Need 82×24 minimum.  ",
            curses.color_pair(C_STATUS) | curses.A_BOLD,
        )
        stdscr.refresh()
        curses.napms(3000)
        return

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
    p_w = max(44, min(width - art_w - 6, 62))
    p_h = art_h
    sx = max(0, (width - art_w - p_w - 2) // 2)
    cy = banner_h + 1

    header_win = curses.newwin(banner_h, width, 0, 0)
    art_win = curses.newwin(art_h, art_w, cy, sx)
    main_win = curses.newwin(p_h, p_w, cy, sx + art_w + 2)
    footer_win = curses.newwin(3, width, height - 3, 0)

    render_header(header_win, banner, width, st)
    S(
        stdscr,
        cy + art_h // 2,
        sx + 2,
        "  ◐  fetching playlist…  ",
        curses.color_pair(C_DIM) | curses.A_DIM,
    )
    stdscr.refresh()

    media = core.extract_media(url)
    if not media or not media.get("tracks"):
        S(
            stdscr,
            cy + art_h // 2,
            sx + 2,
            "  ✕  failed to load media. Check URL and try again.  ",
            curses.color_pair(C_STATUS) | curses.A_BOLD,
        )
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
        st.spin_idx = 0  # Reset so entry ring plays
        st.track_count += 1
        if idx in st.shuffle_pool:
            st.shuffle_pool.remove(idx)
        track = st.queue[idx]
        player.play_stream(track["url"])
        player.set_volume(st.volume)
        st.paused = False
        trigger_art_load(track["url"], art_w, art_h, st)
        st.set_status(f"{CHARS['play']}  {trunc(track['title'] or '…', 40)}")
        
        # Update MPRIS
        if player._HAS_MPRIS:
            import mpris
            mpris.update_mpris_metadata(track)
            mpris.update_mpris_status("Playing")

    # MPRIS Callbacks
    player.on_next = lambda: start_track(st.next_idx())
    player.on_prev = lambda: start_track(st.history.pop() if st.history else st.current_idx - 1, push=False)

    if media["type"] in ("playlist", "search"):
        st.view = "queue"
        st.set_status("Select a track to start playback")
    else:
        start_track(0, push=False)
    _end_armed = False

    while True:
        key = stdscr.getch()
        char = chr(key).lower() if 0 <= key < 256 else ""

        # ── Update EQ simulation ──
        update_eq(paused=st.paused)

        if st.help_open:
            if char in ("?", "q") or key == 27:
                st.help_open = False
            render_header(header_win, banner, width, st)
            render_art_panel(art_win, st, art_w, art_h)
            (render_player_panel if st.view == "player" else render_queue_panel)(
                main_win, st, p_w, p_h
            )
            render_footer(footer_win, width, st)
            render_help_overlay(stdscr, st)
            st.spin_idx += 1
            curses.napms(80)
            continue

        # ── Key handling ──
        if char == "?":
            st.help_open = True

        elif char == "q":
            player.stop_stream()
            break

        elif key == ord("\t"):
            st.view = "queue" if st.view == "player" else "player"
            if st.view == "queue":
                st.sync_cursor_to_current()

        # NEW: Art mode cycle
        elif char == "v":
            modes = ["art", "dancer", "lyrics"]
            idx = modes.index(st.art_mode)
            st.art_mode = modes[(idx + 1) % len(modes)]
            st.set_status(f"view: {st.art_mode}")

        # NEW: Party mode toggle
        elif char == "z":
            st.party_mode = not st.party_mode
            if st.party_mode:
                st.set_status("★  PARTY MODE ON  ★", 2.5)
            else:
                st.set_status("party mode off", 1.5)

        # NEW: EQ toggle
        elif char == "e":
            st.show_eq = not st.show_eq
            st.set_status(f"EQ bars {'on' if st.show_eq else 'off'}", 1.5)

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
                    pos = (
                        visible.index(st.queue_cursor)
                        if st.queue_cursor in visible
                        else 0
                    )
                    st.queue_cursor = visible[max(0, pos - 1)]
            elif key == curses.KEY_DOWN:
                visible = st.visible_indices()
                if visible:
                    pos = (
                        visible.index(st.queue_cursor)
                        if st.queue_cursor in visible
                        else 0
                    )
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
                st.set_status(
                    f"{CHARS['heart']} favorites only"
                    if st.favorites_only
                    else "showing all tracks"
                )
            elif char == "f":
                target = st.queue_cursor
                if target in st.favorites:
                    st.favorites.remove(target)
                    st.set_status("removed from favorites")
                else:
                    st.favorites.add(target)
                    st.set_status(f"{CHARS['heart']} added to favorites")
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
                    st.set_status(
                        f"{CHARS['shuffle_on']}  shuffle on  ·  {len(st.shuffle_pool)} in pool"
                    )
                else:
                    st.shuffle_pool = []
                    st.set_status(f"{CHARS['shuffle_off']}  shuffle off")
            elif char == "l":
                st.repeat = not st.repeat
                st.set_status(
                    f"{CHARS['repeat_on']}  repeat {'on' if st.repeat else 'off'}"
                )
            elif char == "m":
                st.muted = not st.muted
                player.toggle_mute()
                st.set_status(f"{CHARS['mute']}  {'muted' if st.muted else 'unmuted'}")
            elif char == "f":
                if st.current_idx in st.favorites:
                    st.favorites.remove(st.current_idx)
                    st.set_status("removed from favorites")
                else:
                    st.favorites.add(st.current_idx)
                    st.set_status(f"{CHARS['heart']}  added to favorites")
            elif char == "t":
                st.theme_idx = (st.theme_idx + 1) % len(THEMES)
                apply_theme(st)
                st.set_status(f"theme: {THEMES[st.theme_idx]['name']}")
            elif key == curses.KEY_UP:
                st.volume = min(100, st.volume + 5)
                player.set_volume(st.volume)
                st.set_status(f"{CHARS['vol']}  {st.volume}%", 1.5)
            elif key == curses.KEY_DOWN:
                st.volume = max(0, st.volume - 5)
                player.set_volume(st.volume)
                st.set_status(f"{CHARS['vol']}  {st.volume}%", 1.5)
            elif key == curses.KEY_RIGHT:
                player.seek(10)
                st.set_status("⏩  +10 s", 1.0)
            elif key == curses.KEY_LEFT:
                player.seek(-10)
                st.set_status("⏪  −10 s", 1.0)

        # ── Auto-advance ──
        if not st.paused and player.is_running():
            pos = player.get_position()
            dur = player.get_duration()
            # If we are near the end, or mpv has become idle (finished track)
            near = pos is not None and dur and dur > 0 and (dur - pos) < 1.0
            idle = player.is_idle()
            
            if (near or idle) and not _end_armed:
                _end_armed = True
                start_track(
                    st.current_idx if st.repeat else st.next_idx(),
                    push=not st.repeat,
                )
            elif not near and not idle:
                _end_armed = False
        elif not player.is_running() and not st.paused and st.queue:
            # If it's not running and not paused, it must have exited at the end
            start_track(st.next_idx())

        # ── Render ──
        render_header(header_win, banner, width, st)
        render_art_panel(art_win, st, art_w, art_h)
        (render_player_panel if st.view == "player" else render_queue_panel)(
            main_win, st, p_w, p_h
        )
        render_footer(footer_win, width, st)
        if st.help_open:
            render_help_overlay(stdscr, st)

        st.spin_idx += 1
        curses.napms(80)  # slightly faster for smoother EQ animation


if __name__ == "__main__":
    curses.wrapper(run_ui)
