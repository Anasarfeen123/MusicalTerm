"""
MusicalTerm — Terminal Music Player
Aesthetic: Deep space obsidian / iridescent aurora accents
"""

import curses
import threading
import random
import time
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
# Aurora/iridescent color cycle for animated accents
AURORA_CYCLE = [51, 45, 39, 33, 27, 21, 57, 93, 129, 165, 201, 200, 199, 198, 197]

# Color pair IDs
C_ACCENT  = 1   # Primary accent (dynamic aurora color)
C_DIM     = 2   # Muted foreground
C_WHITE   = 3   # Bright white
C_GREEN   = 4   # Volume / progress fill
C_TITLE   = 5   # Header title
C_STATUS  = 6   # Status / warning
C_QUEUE_H = 7   # Queue highlight
C_ART_BG  = 8   # Art panel border
C_CYAN    = 9   # Secondary accent
C_MAGENTA = 10  # Tertiary accent

# ─── Art State ────────────────────────────────────────────────────────────────
art_lock = threading.Lock()
art_data = {"pixels": None, "w": 0, "h": 0, "loading": False, "dom_idx": 51}


# ─── State ────────────────────────────────────────────────────────────────────
class State:
    def __init__(self):
        self.queue          = []
        self.shuffle_pool   = []  # remaining unplayed indices for true shuffle
        self.history        = []
        self.current_idx    = 0
        self.volume         = 70
        self.paused         = False
        self.repeat         = False
        self.shuffle        = False
        self.muted          = False
        self.view           = "player"
        self.queue_offset   = 0
        self._status_msg    = ""
        self._status_ts     = 0
        self.spin_idx       = 0
        self.aurora_phase   = 0

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

    def aurora_color(self):
        return AURORA_CYCLE[self.aurora_phase % len(AURORA_CYCLE)]


# ─── Art Loading ──────────────────────────────────────────────────────────────

def _bg_load_art(url, art_width):
    global art_data
    with art_lock:
        art_data["loading"] = True

    if core.download_thumbnail(url, "cover.jpg"):
        px, w, h, dom_rgb = core.get_album_art_matrix("cover.jpg", size=art_width - 4)
        dom_idx = 16 + int(dom_rgb[0]/255*5)*36 + int(dom_rgb[1]/255*5)*6 + int(dom_rgb[2]/255*5)

        with art_lock:
            art_data.update(pixels=px, w=w, h=h, dom_idx=dom_idx)
            curses.init_pair(C_ART_BG, dom_idx, -1)
            curses.init_pair(C_QUEUE_H, dom_idx, -1)

    with art_lock:
        art_data["loading"] = False


def trigger_art_load(url, art_width):
    threading.Thread(target=_bg_load_art, args=(url, art_width), daemon=True).start()


def draw_art(win, pixels, img_w, img_h):
    """Renders album art using the Half-Block technique for HD color."""
    if not pixels:
        return

    def to256(r, g, b):
        return 16 + int(r/255*5)*36 + int(g/255*5)*6 + int(b/255*5)

    cache, nxt = {}, 15
    for y in range(0, img_h - 1, 2):
        for x in range(img_w):
            idx_top = y * img_w + x
            idx_bot = (y + 1) * img_w + x
            if idx_top >= len(pixels) or idx_bot >= len(pixels):
                continue
            r1, g1, b1 = pixels[idx_top]
            r2, g2, b2 = pixels[idx_bot]
            fg, bg = to256(r1, g1, b1), to256(r2, g2, b2)
            key = (fg, bg)
            if key not in cache:
                if nxt < curses.COLOR_PAIRS:
                    curses.init_pair(nxt, fg, bg)
                    cache[key] = nxt
                    nxt += 1
                else:
                    cache[key] = 0
            try:
                win.addch((y // 2) + 1, x + 1, "▀", curses.color_pair(cache[key]))
            except curses.error:
                pass


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


def update_aurora_pairs(st):
    """Update the animated accent color pairs each tick."""
    ac = st.aurora_color()
    curses.init_pair(C_ACCENT, ac, -1)
    curses.init_pair(C_TITLE,  ac, -1)


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

    title_line = "  ♪  Enter a YouTube / YouTube Music URL  ♪  "
    S(stdscr, cy, max(0, (width - len(title_line))//2), title_line, white | curses.A_BOLD)
    cy += 2

    hint_lines = [
        "Supported formats:",
        "  • Single video   → https://www.youtube.com/watch?v=...",
        "  • Playlist       → https://www.youtube.com/playlist?list=...",
        "  • YT Music song  → https://music.youtube.com/watch?v=...",
        "  • YT Music list  → https://music.youtube.com/playlist?list=...",
        "",
        "Press ENTER to confirm  ·  ESC or Ctrl+C to quit",
    ]
    for line in hint_lines:
        S(stdscr, cy, max(0, (width - 56)//2), line, dim)
        cy += 1

    cy += 1
    box_w  = min(72, width - 6)
    box_x  = max(0, (width - box_w)//2)
    prompt = " URL › "

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
                S(stdscr, err_y, box_x, " Please enter a URL before pressing Enter. ", stat)
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
        dom_idx = art_data.get("dom_idx", st.aurora_color())

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
        draw_art(win, pixels, iw, ih)
    else:
        center_y = art_h // 2
        center_x = art_w // 2
        radius   = min(art_h, art_w) // 3
        for y in range(1, art_h-1):
            for x in range(1, art_w-1):
                dy = y - center_y
                dx = x - center_x
                if dx*dx + dy*dy < radius*radius:
                    S(win, y, x, "•", dim)
        S(win, center_y, center_x-3, "VINYL", border_color | curses.A_BOLD)
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
    counter = f"{st.current_idx+1:02}/{len(st.queue):02}"
    display_title = f"❖ {trunc(title, iw - len(counter) - 6)}"
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

    # Volume bar — green→cyan gradient feel
    vbw   = iw - 10
    vfill = round((st.volume / 100) * vbw)
    vbar  = CHARS["vol_fill"]*vfill + CHARS["vol_empty"]*(vbw-vfill)
    vlabel = f"{CHARS['vol']} {st.volume:3d}%"
    S(win, 6, 2, vlabel, accent | curses.A_BOLD)
    half = vbw // 2
    S(win, 6, 2 + len(vlabel) + 1, vbar[:half], grn)
    S(win, 6, 2 + len(vlabel) + 1 + half, vbar[half:], cyan)

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

    if st.shuffle:
        panel_label(win, f"Q U E U E  ({len(st.queue)})  {CHARS['shuffle_on']} SHUFFLE", p_w, cyan)
    else:
        panel_label(win, f"Q U E U E  ({len(st.queue)})", p_w, accent)

    visible = p_h - 4
    if st.current_idx < st.queue_offset:
        st.queue_offset = st.current_idx
    elif st.current_idx >= st.queue_offset + visible:
        st.queue_offset = st.current_idx - visible + 1

    for i in range(visible):
        idx = st.queue_offset + i
        if idx >= len(st.queue):
            break
        label  = trunc(st.queue[idx].get("title") or "Unknown", p_w - 8)
        is_cur = idx == st.current_idx

        if is_cur:
            S(win, i+2, 1, f" {CHARS['bullet']} {label}", hl | curses.A_BOLD | curses.A_REVERSE)
        elif st.shuffle and idx not in st.shuffle_pool and idx != st.current_idx:
            # Already played this shuffle cycle
            S(win, i+2, 1, f"{idx+1:3}. {label}", dim | curses.A_DIM)
        else:
            S(win, i+2, 1, f"{idx+1:3}. {label}", dim)

    total = len(st.queue)
    if total > visible:
        end  = min(st.queue_offset + visible, total)
        note = f" {st.queue_offset+1}–{end}/{total} "
        S(win, p_h-2, p_w-len(note)-1, note, dim | curses.A_DIM)

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
        keys = [("Q","quit"),("P","pause"),("R","resume"),("N","next"),
                ("B","back"),("S","shuffle"),("L","loop"),("M","mute"),
                ("↑↓","vol"),("←→","seek"),("TAB","queue")]
    else:
        keys = [("TAB","player"),("↑↓","scroll"),("↵","play"),("Q","quit")]

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

    # Deep space / aurora theme
    curses.init_pair(C_ACCENT,  51,  -1)   # Electric cyan
    curses.init_pair(C_DIM,    238,  -1)   # Dark grey
    curses.init_pair(C_WHITE,  255,  -1)   # Bright white
    curses.init_pair(C_GREEN,   84,  -1)   # Neon green
    curses.init_pair(C_TITLE,   51,  -1)   # Electric cyan title
    curses.init_pair(C_STATUS, 203,  -1)   # Warm red/orange
    curses.init_pair(C_QUEUE_H, 51,  -1)   # Matches accent
    curses.init_pair(C_ART_BG,  57,  -1)   # Deep indigo
    curses.init_pair(C_CYAN,    87,  -1)   # Bright cyan
    curses.init_pair(C_MAGENTA,201,  -1)   # Hot magenta

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

    banner   = f_title.renderText("MT").splitlines()
    banner_h = len(banner) + 1
    art_w, art_h = 40, 20
    p_w  = min(width - art_w - 6, 58)
    p_h  = art_h
    sx   = max(0, (width - art_w - p_w - 2) // 2)
    cy   = banner_h + 1

    header_win = curses.newwin(banner_h, width,   0,        0)
    art_win    = curses.newwin(art_h,    art_w,   cy,       sx)
    main_win   = curses.newwin(p_h,      p_w,     cy,       sx + art_w + 2)
    footer_win = curses.newwin(3,        width,   height-3, 0)

    st = State()
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
    st.reset_shuffle_pool()

    def start_track(idx, push=True):
        if push and st.current_idx != idx:
            st.history.append(st.current_idx)
        st.current_idx = idx
        if idx in st.shuffle_pool:
            st.shuffle_pool.remove(idx)
        track = st.queue[idx]
        player.play_stream(track["url"])
        player.set_volume(st.volume)
        st.paused = False
        trigger_art_load(track["url"], art_w)
        st.set_status(f"{CHARS['play']}  {trunc(track['title'] or '…', 40)}")

    start_track(0, push=False)
    _end_armed = False

    while True:
        key = stdscr.getch()

        if key == ord("q"):
            player.stop_stream()
            break

        elif key == ord("\t"):
            st.view = "queue" if st.view == "player" else "player"

        elif st.view == "queue":
            if   key == curses.KEY_UP:   st.queue_offset = max(0, st.queue_offset-1)
            elif key == curses.KEY_DOWN: st.queue_offset = min(len(st.queue)-1, st.queue_offset+1)
            elif key in [ord("\n"), curses.KEY_ENTER]:
                start_track(st.queue_offset)
                st.view = "player"

        else:
            if key == ord("n"):
                start_track(st.next_idx())
            elif key == ord("b"):
                if st.history:
                    start_track(st.history.pop(), push=False)
                elif st.current_idx > 0:
                    start_track(st.current_idx - 1)
            elif key == ord("p"):
                player.pause_stream()
                st.paused = True
                st.set_status(f"{CHARS['pause']}  paused")
            elif key == ord("r"):
                player.resume_stream()
                st.paused = False
                st.set_status(f"{CHARS['play']}  resumed")
            elif key == ord("s"):
                st.shuffle = not st.shuffle
                if st.shuffle:
                    st.reset_shuffle_pool()
                    st.set_status(f"{CHARS['shuffle_on']}  shuffle on  ·  {len(st.shuffle_pool)} tracks in pool")
                else:
                    st.shuffle_pool = []
                    st.set_status(f"{CHARS['shuffle_off']}  shuffle off")
            elif key == ord("l"):
                st.repeat = not st.repeat
                st.set_status(f"{CHARS['repeat_on']}  repeat {'on' if st.repeat else 'off'}")
            elif key == ord("m"):
                st.muted = not st.muted
                player.toggle_mute()
                st.set_status(f"{CHARS['mute']}  {'muted' if st.muted else 'unmuted'}")
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

        # Aurora animation tick
        if st.spin_idx % 8 == 0:
            st.aurora_phase = (st.aurora_phase + 1) % len(AURORA_CYCLE)
            update_aurora_pairs(st)

        # Render
        render_header(header_win, banner, width, st)
        render_art_panel(art_win, st, art_w, art_h)
        (render_player_panel if st.view == "player" else render_queue_panel)(
            main_win, st, p_w, p_h)
        render_footer(footer_win, width, st)

        st.spin_idx += 1
        curses.napms(100)


if __name__ == "__main__":
    curses.wrapper(run_ui)