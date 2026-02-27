import curses
import threading
import random
import time
from pyfiglet import Figlet
import core
import player

f = Figlet(font="slant")

# ─── Art State ────────────────────────────────────────────────────────────────
art_lock = threading.Lock()
art_data = {"pixels": None, "w": 0, "h": 0, "loading": False, "url": None}

# ─── Playback State ───────────────────────────────────────────────────────────
class State:
    def __init__(self):
        self.queue         = []
        self.history       = []          # for back-tracking
        self.current_idx   = 0
        self.volume        = 70
        self.paused        = False
        self.repeat        = False       # repeat current track
        self.shuffle       = False
        self.view          = "player"    # "player" | "queue"
        self.queue_offset  = 0          # scroll offset for queue view
        self.status_msg    = ""
        self.status_ts     = 0
        self.spin_idx      = 0

    def set_status(self, msg):
        self.status_msg = msg
        self.status_ts  = time.time()

    def get_status(self):
        if time.time() - self.status_ts < 3:
            return self.status_msg
        return ""

    def next_idx(self):
        if self.shuffle:
            return random.randrange(len(self.queue))
        return (self.current_idx + 1) % len(self.queue)

    def prev_idx(self):
        if self.history:
            return self.history[-1]
        return max(0, self.current_idx - 1)


# ─── Art Loading ──────────────────────────────────────────────────────────────

def bg_update_art(url, art_width):
    with art_lock:
        art_data["loading"] = True
        art_data["pixels"]  = None
        art_data["url"]     = url

    if core.download_thumbnail(url, "cover.jpg"):
        px, w, h = core.get_album_art_matrix("cover.jpg", size=art_width - 4)
        with art_lock:
            art_data["pixels"] = px
            art_data["w"]      = w
            art_data["h"]      = h

    with art_lock:
        art_data["loading"] = False


def trigger_art_load(url, art_width):
    t = threading.Thread(target=bg_update_art, args=(url, art_width), daemon=True)
    t.start()


def draw_art(win, pixels, img_w, img_h):
    if not pixels:
        return

    def rgb_to_256(r, g, b):
        return 16 + int(r / 255 * 5) * 36 + int(g / 255 * 5) * 6 + int(b / 255 * 5)

    pair_cache  = {}
    next_pair_id = 10

    for y in range(0, img_h - 1, 2):
        for x in range(img_w):
            ti = y * img_w + x
            bi = (y + 1) * img_w + x
            if ti >= len(pixels) or bi >= len(pixels):
                continue

            r1, g1, b1 = pixels[ti]
            r2, g2, b2 = pixels[bi]
            fg = rgb_to_256(r1, g1, b1)
            bg = rgb_to_256(r2, g2, b2)
            key = (fg, bg)

            if key not in pair_cache:
                if next_pair_id < curses.COLOR_PAIRS:
                    curses.init_pair(next_pair_id, fg, bg)
                    pair_cache[key] = next_pair_id
                    next_pair_id += 1
                else:
                    pair_cache[key] = 0

            try:
                win.addch((y // 2) + 1, x + 1, "▀", curses.color_pair(pair_cache[key]))
            except curses.error:
                pass


# ─── UI Components ────────────────────────────────────────────────────────────

def draw_border_titled(win, title, color_pair=1):
    win.erase()
    win.attron(curses.color_pair(color_pair))
    win.border()
    win.attroff(curses.color_pair(color_pair))
    if title:
        label = f" {title} "
        try:
            win.addstr(0, 2, label, curses.color_pair(color_pair) | curses.A_BOLD)
        except curses.error:
            pass


def draw_progress_bar(win, y, x, width, progress):
    if width < 10:
        return
    bar_w   = width - 10
    filled  = int(progress * bar_w)
    bar     = "█" * filled + "░" * (bar_w - filled)
    pct     = f"{int(progress * 100):3d}%"
    try:
        win.addstr(y, x,              "▕", curses.color_pair(3))
        win.addstr(y, x + 1,          bar, curses.color_pair(3))
        win.addstr(y, x + bar_w + 1,  "▏", curses.color_pair(3))
        win.addstr(y, x + bar_w + 3,  pct, curses.A_BOLD)
    except curses.error:
        pass


def fmt_time(secs):
    if secs is None:
        return "--:--"
    m, s = divmod(int(secs), 60)
    return f"{m:02}:{s:02}"


def draw_player_panel(win, st: State, p_w, p_h, spinner):
    draw_border_titled(win, "NOW PLAYING")

    track = st.queue[st.current_idx] if st.queue else None
    title = track["title"] if track else "No track"

    max_title = p_w - 6
    display   = (title[:max_title - 2] + "..") if len(title) > max_title else title

    # Title
    try:
        win.addstr(2, 3, display, curses.color_pair(1) | curses.A_BOLD)
    except curses.error:
        pass

    # Track counter
    counter = f"{st.current_idx + 1}/{len(st.queue)}"
    try:
        win.addstr(2, p_w - len(counter) - 2, counter, curses.color_pair(5))
    except curses.error:
        pass

    # Status flags
    flags = []
    if st.shuffle: flags.append("⇀ SHUFFLE")
    if st.repeat:  flags.append("↺ REPEAT")
    if st.paused:  flags.append("⏸ PAUSED")
    flag_str = "  ".join(flags)
    try:
        win.addstr(3, 3, flag_str, curses.color_pair(2))
    except curses.error:
        pass

    # Volume bar
    vol_bar_w = min(20, p_w - 16)
    vol_filled = int((st.volume / 100) * vol_bar_w)
    vol_bar = "▮" * vol_filled + "▯" * (vol_bar_w - vol_filled)
    try:
        win.addstr(5, 3, f"VOL  {vol_bar}  {st.volume:3d}%", curses.color_pair(2))
    except curses.error:
        pass

    # Time & progress
    elapsed  = player.get_position()
    duration = player.get_duration()

    if elapsed is not None and duration and duration > 0:
        time_str = f"{fmt_time(elapsed)} / {fmt_time(duration)}"
        try:
            win.addstr(p_h - 4, 3, time_str, curses.color_pair(5))
        except curses.error:
            pass
        draw_progress_bar(win, p_h - 3, 3, p_w - 6, min(1.0, elapsed / duration))
    else:
        try:
            win.addstr(p_h - 3, 3,
                       f"{spinner[st.spin_idx % len(spinner)]}  Buffering...",
                       curses.A_DIM)
        except curses.error:
            pass

    # Inline status message
    status = st.get_status()
    if status:
        try:
            win.addstr(p_h - 2, 3, status, curses.color_pair(2) | curses.A_DIM)
        except curses.error:
            pass

    win.refresh()


def draw_queue_panel(win, st: State, p_w, p_h):
    draw_border_titled(win, "QUEUE")

    visible = p_h - 3
    total   = len(st.queue)

    # Clamp scroll so current track is always visible
    if st.current_idx < st.queue_offset:
        st.queue_offset = st.current_idx
    elif st.current_idx >= st.queue_offset + visible:
        st.queue_offset = st.current_idx - visible + 1

    for i in range(visible):
        idx = st.queue_offset + i
        if idx >= total:
            break
        track   = st.queue[idx]
        label   = track["title"] or "Unknown"
        label   = (label[:p_w - 8] + "..") if len(label) > p_w - 8 else label
        row     = i + 1
        is_cur  = idx == st.current_idx

        prefix = "▶ " if is_cur else f"{idx+1:2}. "
        try:
            attr = (curses.color_pair(1) | curses.A_BOLD) if is_cur else curses.color_pair(5)
            win.addstr(row, 2, prefix + label, attr)
        except curses.error:
            pass

    # Scroll indicator
    if total > visible:
        scroll_pct = f"  {st.queue_offset + 1}-{min(st.queue_offset + visible, total)}/{total}"
        try:
            win.addstr(p_h - 1, p_w - len(scroll_pct) - 1, scroll_pct, curses.color_pair(5) | curses.A_DIM)
        except curses.error:
            pass

    win.refresh()


def draw_footer(win, width, view):
    win.erase()
    if view == "player":
        help_str = " [Q]uit [P]ause [R]esume [N]ext [B]ack [S]huffle [L]oop [↑↓]Vol [←→]Seek [TAB]Queue "
    else:
        help_str = " [TAB]Back to Player  [↑↓]Scroll Queue "
    x = max(0, (width - len(help_str)) // 2)
    try:
        win.addstr(0, x, help_str, curses.color_pair(4) | curses.A_DIM)
    except curses.error:
        pass
    win.refresh()


def draw_header(win, banner, width):
    win.erase()
    for i, line in enumerate(banner):
        x = max(0, (width - len(line)) // 2)
        try:
            win.addstr(i, x, line, curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass
    win.refresh()


# ─── Main UI Loop ─────────────────────────────────────────────────────────────

def run_ui(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    stdscr.nodelay(True)
    stdscr.keypad(True)

    curses.init_pair(1, curses.COLOR_CYAN,    -1)   # Accent / titles
    curses.init_pair(2, curses.COLOR_YELLOW,  -1)   # Status / flags
    curses.init_pair(3, curses.COLOR_GREEN,   -1)   # Progress bar
    curses.init_pair(4, curses.COLOR_WHITE,   -1)   # Footer
    curses.init_pair(5, 245,                  -1)   # Muted text (gray)

    height, width = stdscr.getmaxyx()
    if height < 24 or width < 80:
        stdscr.addstr(0, 0, f"Terminal too small ({width}x{height}). Need 80x24 min.")
        stdscr.refresh()
        curses.napms(2500)
        return

    banner   = f.renderText("MusicalTerm").splitlines()
    banner_h = len(banner)

    art_w = 42
    art_h = 20
    p_w   = min(width - art_w - 8, 55)
    p_h   = art_h

    total_ui_w = art_w + p_w + 4
    start_x    = (width - total_ui_w) // 2

    header_win = curses.newwin(banner_h + 1, width,  1,              0)
    art_win    = curses.newwin(art_h,        art_w,  banner_h + 2,   start_x)
    main_win   = curses.newwin(p_h,          p_w,    banner_h + 2,   start_x + art_w + 2)
    footer_win = curses.newwin(2,            width,  height - 2,     0)

    draw_header(header_win, banner, width)

    # ── Load media ──
    url   = "https://music.youtube.com/playlist?list=PLF09LSCsr9VMLI8WhNk9Mu7dYawruYBDi"
    media = core.extract_media(url)

    if not media or not media.get("tracks"):
        stdscr.addstr(height // 2, width // 2 - 12,
                      "  FAILED TO LOAD MEDIA  ", curses.color_pair(2) | curses.A_BOLD)
        stdscr.refresh()
        curses.napms(2500)
        return

    st          = State()
    st.queue    = media["tracks"]
    st.volume   = 70
    spinner     = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

    def start_track(idx, push_history=True):
        if push_history and st.current_idx != idx:
            st.history.append(st.current_idx)
        st.current_idx = idx
        track = st.queue[idx]
        player.play_stream(track["url"])
        player.set_volume(st.volume)
        st.paused = False
        trigger_art_load(track["url"], art_w)
        st.set_status(f"▶  {track['title'][:40]}")

    start_track(st.current_idx, push_history=False)

    last_track_end = False

    while True:
        key = stdscr.getch()

        # ── Handle key input ──
        if key == ord("q"):
            player.stop_stream()
            break

        elif key == ord("\t"):                     # TAB: toggle view
            st.view = "queue" if st.view == "player" else "player"

        elif st.view == "queue":
            if key == curses.KEY_UP:
                st.queue_offset = max(0, st.queue_offset - 1)
            elif key == curses.KEY_DOWN:
                st.queue_offset = min(len(st.queue) - 1, st.queue_offset + 1)
            elif key in [ord("\n"), curses.KEY_ENTER]:
                start_track(st.queue_offset)

        else:  # player view keys
            if key == ord("n"):
                nxt = st.next_idx()
                start_track(nxt)
            elif key == ord("b"):
                if st.history:
                    prev = st.history.pop()
                    start_track(prev, push_history=False)
                elif st.current_idx > 0:
                    start_track(st.current_idx - 1)
            elif key == ord("p"):
                player.pause_stream()
                st.paused = True
                st.set_status("⏸  Paused")
            elif key == ord("r"):
                player.resume_stream()
                st.paused = False
                st.set_status("▶  Resumed")
            elif key == ord("s"):
                st.shuffle = not st.shuffle
                st.set_status(f"⇀ Shuffle {'ON' if st.shuffle else 'OFF'}")
            elif key == ord("l"):
                st.repeat = not st.repeat
                st.set_status(f"↺ Repeat {'ON' if st.repeat else 'OFF'}")
            elif key == curses.KEY_UP:
                st.volume = min(100, st.volume + 5)
                player.set_volume(st.volume)
                st.set_status(f"🔊 Volume {st.volume}%")
            elif key == curses.KEY_DOWN:
                st.volume = max(0, st.volume - 5)
                player.set_volume(st.volume)
                st.set_status(f"🔊 Volume {st.volume}%")
            elif key == curses.KEY_RIGHT:
                player.seek(10)
                st.set_status("⏩ +10s")
            elif key == curses.KEY_LEFT:
                player.seek(-10)
                st.set_status("⏪ -10s")
            elif key == ord("m"):
                player.toggle_mute()
                st.set_status("🔇 Mute toggled")

        # ── Auto-advance when track ends ──
        if not st.paused and player.is_running():
            pos = player.get_position()
            dur = player.get_duration()
            if pos is not None and dur and dur > 0 and dur - pos < 0.5:
                if not last_track_end:
                    last_track_end = True
                    if st.repeat:
                        start_track(st.current_idx, push_history=False)
                    else:
                        start_track(st.next_idx())
            else:
                last_track_end = False
        elif not player.is_running() and not st.paused and st.queue:
            # mpv died unexpectedly — advance
            start_track(st.next_idx())

        # ── Draw Art ──
        draw_border_titled(art_win, "ALBUM ART")
        with art_lock:
            if art_data["loading"]:
                art_win.addstr(art_h // 2, (art_w // 2) - 6,
                               f"{spinner[st.spin_idx % 10]}  Loading…",
                               curses.A_DIM)
            elif art_data["pixels"]:
                draw_art(art_win, art_data["pixels"], art_data["w"], art_data["h"])
            else:
                art_win.addstr(art_h // 2, (art_w // 2) - 7,
                               "  No Thumbnail  ", curses.A_DIM)
        art_win.refresh()

        # ── Draw Main Panel ──
        if st.view == "player":
            draw_player_panel(main_win, st, p_w, p_h, spinner)
        else:
            draw_queue_panel(main_win, st, p_w, p_h)

        draw_footer(footer_win, width, st.view)

        st.spin_idx += 1
        curses.napms(100)


if __name__ == "__main__":
    curses.wrapper(run_ui)