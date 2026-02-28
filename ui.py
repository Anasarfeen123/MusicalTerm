"""
MusicalTerm — Terminal Music Player
Aesthetic: Luxury vinyl / dark obsidian / warm gold accents
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
    "h_line":      "─",
    "v_line":      "│",
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

# Color pair IDs
C_GOLD   = 1
C_DIM    = 2
C_WHITE  = 3
C_GREEN  = 4
C_TITLE  = 5
C_STATUS = 6
C_QUEUE_H = 7

# ─── Art State ────────────────────────────────────────────────────────────────
art_lock = threading.Lock()
art_data = {"pixels": None, "w": 0, "h": 0, "loading": False}


# ─── State ────────────────────────────────────────────────────────────────────
class State:
    def __init__(self):
        self.queue        = []
        self.history      = []
        self.current_idx  = 0
        self.volume       = 70
        self.paused       = False
        self.repeat       = False
        self.shuffle      = False
        self.muted        = False
        self.view         = "player"
        self.queue_offset = 0
        self._status_msg  = ""
        self._status_ts   = 0
        self.spin_idx     = 0

    def set_status(self, msg, ttl=3.0):
        self._status_msg = msg
        self._status_ts  = time.time() + ttl

    def get_status(self):
        return self._status_msg if time.time() < self._status_ts else ""

    def next_idx(self):
        if self.shuffle:
            choices = [i for i in range(len(self.queue)) if i != self.current_idx]
            return random.choice(choices) if choices else self.current_idx
        return (self.current_idx + 1) % len(self.queue)


# ─── Art Loading ──────────────────────────────────────────────────────────────

def _bg_load_art(url, art_width):
    with art_lock:
        art_data["loading"] = True
        art_data["pixels"]  = None
    if core.download_thumbnail(url, "cover.jpg"):
        px, w, h = core.get_album_art_matrix("cover.jpg", size=art_width - 4)
        with art_lock:
            art_data.update(pixels=px, w=w, h=h)
    with art_lock:
        art_data["loading"] = False


def trigger_art_load(url, art_width):
    threading.Thread(target=_bg_load_art, args=(url, art_width), daemon=True).start()


def draw_art(win, pixels, img_w, img_h):
    if not pixels:
        return
    def to256(r, g, b):
        return 16 + int(r/255*5)*36 + int(g/255*5)*6 + int(b/255*5)
    cache, nxt = {}, 10
    for y in range(0, img_h - 1, 2):
        for x in range(img_w):
            ti = y * img_w + x
            bi = (y+1) * img_w + x
            if ti >= len(pixels) or bi >= len(pixels):
                continue
            r1,g1,b1 = pixels[ti]
            r2,g2,b2 = pixels[bi]
            fg, bg = to256(r1,g1,b1), to256(r2,g2,b2)
            key = (fg, bg)
            if key not in cache:
                if nxt < curses.COLOR_PAIRS:
                    curses.init_pair(nxt, fg, bg)
                    cache[key] = nxt; nxt += 1
                else:
                    cache[key] = 0
            try:
                win.addch((y//2)+1, x+1, "▀", curses.color_pair(cache[key]))
            except curses.error:
                pass


# ─── Primitives ───────────────────────────────────────────────────────────────

def S(win, y, x, text, attr=0):
    try: win.addstr(y, x, text, attr)
    except curses.error: pass


def draw_box(win, h, w, cp):
    c = CHARS
    S(win, 0,   0,   c["tl"] + c["h_line"]*(w-2) + c["tr"], cp)
    S(win, h-1, 0,   c["bl"] + c["h_line"]*(w-2) + c["br"], cp)
    for r in range(1, h-1):
        S(win, r, 0,   c["v_line"], cp)
        S(win, r, w-1, c["v_line"], cp)


def draw_hrule(win, y, x, w, cp):
    S(win, y, x,       CHARS["t_left"],         cp)
    S(win, y, x+1,     CHARS["h_line"]*(w-2),   cp)
    S(win, y, x+w-1,   CHARS["t_right"],         cp)


def panel_label(win, text, w, cp):
    label = f"  {text}  "
    S(win, 0, max(2, (w - len(label))//2), label, cp | curses.A_BOLD)


def trunc(s, n):
    return (s[:n-1] + "…") if len(s) > n else s


def fmt_t(s):
    if s is None: return "--:--"
    m, sec = divmod(int(s), 60)
    return f"{m:02}:{sec:02}"


# ─── Panels ───────────────────────────────────────────────────────────────────

def render_art_panel(win, st, art_w, art_h):
    win.erase()
    gold = curses.color_pair(C_GOLD)
    dim  = curses.color_pair(C_DIM)
    draw_box(win, art_h, art_w, gold)
    panel_label(win, "A L B U M", art_w, gold)

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
        S(win, art_h//2, (art_w-14)//2, "  no thumbnail  ", dim | curses.A_DIM)
    win.refresh()


def render_player_panel(win, st, p_w, p_h):
    win.erase()
    gold  = curses.color_pair(C_GOLD)
    dim   = curses.color_pair(C_DIM)
    white = curses.color_pair(C_WHITE)
    grn   = curses.color_pair(C_GREEN)
    stat  = curses.color_pair(C_STATUS)
    iw    = p_w - 4

    draw_box(win, p_h, p_w, gold)
    panel_label(win, "N O W  P L A Y I N G", p_w, gold)

    # Title + counter
    track   = st.queue[st.current_idx] if st.queue else None
    title   = track["title"] if track else "No track loaded"
    counter = f"{st.current_idx+1:02}/{len(st.queue):02}"
    S(win, 2, 2, trunc(title, iw - len(counter) - 2), white | curses.A_BOLD)
    S(win, 2, p_w - len(counter) - 2, counter, dim)

    draw_hrule(win, 3, 0, p_w, gold)

    # Mode flags
    flags = [
        (CHARS["pause"] if st.paused else CHARS["play"],
         "PAUSED" if st.paused else "PLAYING",
         stat if st.paused else white),
        (CHARS["shuffle_on"] if st.shuffle else CHARS["shuffle_off"],
         "SHUFFLE",
         gold if st.shuffle else dim),
        (CHARS["repeat_on"] if st.repeat else CHARS["repeat_off"],
         "REPEAT",
         gold if st.repeat else dim),
    ]
    if st.muted:
        flags.append((CHARS["mute"], "MUTED", stat))

    cx = 2
    for icon, lbl, attr in flags:
        seg = f"{icon} {lbl}  "
        S(win, 4, cx, seg, attr)
        cx += len(seg)

    draw_hrule(win, 5, 0, p_w, gold)

    # Volume
    vbw    = iw - 10
    vfill  = round((st.volume / 100) * vbw)
    vbar   = CHARS["vol_fill"]*vfill + CHARS["vol_empty"]*(vbw-vfill)
    vlabel = f"{CHARS['vol']} {st.volume:3d}%"
    S(win, 6, 2, vlabel, gold | curses.A_BOLD)
    S(win, 6, 2 + len(vlabel) + 1, vbar, grn)

    draw_hrule(win, p_h - 5, 0, p_w, gold)

    # Progress
    elapsed  = player.get_position()
    duration = player.get_duration()
    if elapsed is not None and duration and duration > 0:
        prog   = min(1.0, elapsed / duration)
        bw     = iw - 2
        filled = round(prog * bw)
        bar    = CHARS["bar_fill"]*filled + CHARS["bar_empty"]*(bw-filled)
        tstr   = f"{fmt_t(elapsed)}  {CHARS['arrow']}  {fmt_t(duration)}"
        S(win, p_h-4, 2, tstr, dim)
        S(win, p_h-3, 2, bar,  grn | curses.A_BOLD)
        S(win, p_h-3, p_w - 5, f"{int(prog*100):3d}%", gold)
    else:
        sp = CHARS["spin"][st.spin_idx % 4]
        S(win, p_h-4, 2, f"{sp}  buffering…", dim | curses.A_DIM)

    # Status
    status = st.get_status()
    if status:
        S(win, p_h-2, 2, trunc(status, iw), stat | curses.A_DIM)

    win.refresh()


def render_queue_panel(win, st, p_w, p_h):
    win.erase()
    gold  = curses.color_pair(C_GOLD)
    dim   = curses.color_pair(C_DIM)
    hl    = curses.color_pair(C_QUEUE_H)

    draw_box(win, p_h, p_w, gold)
    panel_label(win, f"Q U E U E  ({len(st.queue)})", p_w, gold)

    visible = p_h - 4
    if st.current_idx < st.queue_offset:
        st.queue_offset = st.current_idx
    elif st.current_idx >= st.queue_offset + visible:
        st.queue_offset = st.current_idx - visible + 1

    for i in range(visible):
        idx = st.queue_offset + i
        if idx >= len(st.queue): break
        label  = trunc(st.queue[idx].get("title") or "Unknown", p_w - 8)
        is_cur = idx == st.current_idx
        if is_cur:
            S(win, i+2, 1, f" {CHARS['bullet']} {label}", hl | curses.A_BOLD)
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
    gold = curses.color_pair(C_GOLD)
    dim  = curses.color_pair(C_DIM)

    try:
        win.addstr(0, 0, CHARS["h_line"] * (width - 1), gold)
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
        S(win, 1, cx, f" {k} ", gold | curses.A_BOLD)
        cx += len(k) + 2
        S(win, 1, cx, f"{CHARS['dot']} {v} ", dim)
        cx += len(v) + 4
        if i < len(keys) - 1:
            S(win, 1, cx, CHARS["v_line"], gold)
            cx += 1

    win.refresh()


def render_header(win, banner, width):
    win.erase()
    gold = curses.color_pair(C_TITLE)
    for i, line in enumerate(banner):
        S(win, i, max(0, (width - len(line))//2), line, gold | curses.A_BOLD)
    win.refresh()


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_ui(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    stdscr.nodelay(True)
    stdscr.keypad(True)

    curses.init_pair(C_GOLD,    214, -1)
    curses.init_pair(C_DIM,     242, -1)
    curses.init_pair(C_WHITE,   255, -1)
    curses.init_pair(C_GREEN,   149, -1)
    curses.init_pair(C_TITLE,   220, -1)
    curses.init_pair(C_STATUS,  208, -1)
    curses.init_pair(C_QUEUE_H, 214, -1)

    height, width = stdscr.getmaxyx()
    if height < 24 or width < 82:
        S(stdscr, 0, 0,
          f"  Terminal too small ({width}×{height}). Need 82×24 minimum.  ",
          curses.color_pair(C_STATUS) | curses.A_BOLD)
        stdscr.refresh()
        curses.napms(3000)
        return

    banner   = f_title.renderText("MT").splitlines()
    banner_h = len(banner) + 1
    art_w, art_h = 40, 20
    p_w  = min(width - art_w - 6, 58)
    p_h  = art_h
    sx   = max(0, (width - art_w - p_w - 2) // 2)
    cy   = banner_h + 1

    header_win = curses.newwin(banner_h, width, 0,      0)
    art_win    = curses.newwin(art_h,    art_w, cy,     sx)
    main_win   = curses.newwin(p_h,      p_w,   cy,     sx + art_w + 2)
    footer_win = curses.newwin(3,        width, height-3, 0)

    render_header(header_win, banner, width)

    # Loading indicator
    S(stdscr, cy + art_h//2, sx + 2, "  ◐  fetching playlist…  ",
      curses.color_pair(C_DIM) | curses.A_DIM)
    stdscr.refresh()

    media = core.extract_media(
        "https://music.youtube.com/playlist?list=PLF09LSCsr9VMLI8WhNk9Mu7dYawruYBDi"
    )
    if not media or not media.get("tracks"):
        S(stdscr, cy + art_h//2, sx + 2, "  ✕  failed to load media.  ",
          curses.color_pair(C_STATUS) | curses.A_BOLD)
        stdscr.refresh()
        curses.napms(3000)
        return

    st       = State()
    st.queue = media["tracks"]

    def start_track(idx, push=True):
        if push and st.current_idx != idx:
            st.history.append(st.current_idx)
        st.current_idx = idx
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
            player.stop_stream(); break

        elif key == ord("\t"):
            st.view = "queue" if st.view == "player" else "player"

        elif st.view == "queue":
            if   key == curses.KEY_UP:   st.queue_offset = max(0, st.queue_offset-1)
            elif key == curses.KEY_DOWN: st.queue_offset = min(len(st.queue)-1, st.queue_offset+1)
            elif key in [ord("\n"), curses.KEY_ENTER]:
                start_track(st.queue_offset); st.view = "player"

        else:
            if   key == ord("n"):           start_track(st.next_idx())
            elif key == ord("b"):
                if st.history:              start_track(st.history.pop(), push=False)
                elif st.current_idx > 0:    start_track(st.current_idx-1)
            elif key == ord("p"):           player.pause_stream();  st.paused = True;  st.set_status(f"{CHARS['pause']}  paused")
            elif key == ord("r"):           player.resume_stream(); st.paused = False; st.set_status(f"{CHARS['play']}  resumed")
            elif key == ord("s"):           st.shuffle = not st.shuffle; st.set_status(f"{CHARS['shuffle_on']}  shuffle {'on' if st.shuffle else 'off'}")
            elif key == ord("l"):           st.repeat  = not st.repeat;  st.set_status(f"{CHARS['repeat_on']}  repeat {'on' if st.repeat else 'off'}")
            elif key == ord("m"):           st.muted = not st.muted; player.toggle_mute(); st.set_status(f"{CHARS['mute']}  {'muted' if st.muted else 'unmuted'}")
            elif key == curses.KEY_UP:      st.volume = min(100, st.volume+5);  player.set_volume(st.volume); st.set_status(f"{CHARS['vol']}  {st.volume}%", 1.5)
            elif key == curses.KEY_DOWN:    st.volume = max(0,   st.volume-5);  player.set_volume(st.volume); st.set_status(f"{CHARS['vol']}  {st.volume}%", 1.5)
            elif key == curses.KEY_RIGHT:   player.seek(10);  st.set_status("⏩  +10 s", 1.0)
            elif key == curses.KEY_LEFT:    player.seek(-10); st.set_status("⏪  −10 s", 1.0)

        # Auto-advance
        if not st.paused and player.is_running():
            pos = player.get_position()
            dur = player.get_duration()
            near = pos is not None and dur and dur > 0 and (dur - pos) < 0.8
            if near and not _end_armed:
                _end_armed = True
                start_track(st.current_idx if st.repeat else st.next_idx(),
                             push=not st.repeat)
            elif not near:
                _end_armed = False
        elif not player.is_running() and not st.paused and st.queue:
            start_track(st.next_idx())

        # Render
        render_art_panel(art_win, st, art_w, art_h)
        (render_player_panel if st.view == "player" else render_queue_panel)(
            main_win, st, p_w, p_h)
        render_footer(footer_win, width, st)

        st.spin_idx += 1
        curses.napms(100)


if __name__ == "__main__":
    curses.wrapper(run_ui)