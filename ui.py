import curses
from pyfiglet import Figlet
import threading
import logging
import player
import core

# Initialize Figlet
f = Figlet(font="future")

logging.basicConfig(
    filename="musicalterm_crash.log",
    level=logging.DEBUG
)

def safe_play(url):
    try:
        player.play_stream(url)
    except Exception as e:
        logging.exception(f"Playback thread crashed: {e}")

def handle_single_track(track):
    return [track]

def handle_playlist(tracks):
    return tracks

def draw_progress_bar(win, y, x, width, progress):
    """Draws a styled progress bar with percentage."""
    if width < 5: return
    bar_width = width - 8
    bar_length = int(progress * bar_width)
    
    # Progress bar string
    bar = "█" * bar_length + "░" * (bar_width - bar_length)

    # Color selection based on progress
    if progress < 0.3:
        color = curses.color_pair(4)  # Yellow
    elif progress < 0.8:
        color = curses.color_pair(3)  # Green
    else:
        color = curses.color_pair(2)  # Cyan

    win.attron(color)
    win.addstr(y, x, bar)
    win.attroff(color)
    win.addstr(y, x + bar_width + 1, f"{int(progress * 100):3d}%")

def draw_header(win, banner, width):
    """Refreshes the banner at the top center."""
    win.erase()
    for i, line in enumerate(banner):
        x = max(0, (width - len(line)) // 2)
        win.addstr(i, x, line[:width - 1], curses.color_pair(1) | curses.A_BOLD)
    win.refresh()

def main(stdscr):
    # Setup Curses Colors
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    
    # Pairs: (ID, Foreground, Background)
    curses.init_pair(1, curses.COLOR_RED, -1)     # Banner
    curses.init_pair(2, curses.COLOR_CYAN, -1)    # Title / Info
    curses.init_pair(3, curses.COLOR_GREEN, -1)   # Progress High
    curses.init_pair(4, curses.COLOR_YELLOW, -1)  # Progress Low / Warning

    stdscr.nodelay(True)
    stdscr.keypad(True)

    # --- Layout Calculations ---
    height, width = stdscr.getmaxyx()
    banner_text = f.renderText("MusicalTerm").splitlines()
    if len(banner_text) + 14 > height:
        banner_text = ["  MUSICALTERM  "]
    
    banner_h = len(banner_text)
    header_win = curses.newwin(banner_h, width, 1, 0)
    
    # Player box settings
    p_h, p_w = 10, min(width - 6, 80)
    p_y, p_x = banner_h + 2, (width - p_w) // 2
    player_win = curses.newwin(p_h, p_w, p_y, p_x)
    
    # Footer settings
    footer_win = curses.newwin(2, width, p_y + p_h + 1, 0)

    # --- Load Content ---
    draw_header(header_win, banner_text, width)
    
    # Use the playlist or specific video
    url = "https://music.youtube.com/playlist?list=PLl578ZPbYIlFcSxuka8Km37VgbUYUWI5p"
    media = core.extract_media(url)
    if not media:
        stdscr.addstr(height//2, (width-20)//2, "Failed to load stream.")
        stdscr.refresh()
        curses.napms(2000)
        return

    if media["type"] == "video":
        queue = handle_single_track(media["tracks"][0])
    else:
        queue = handle_playlist(media["tracks"])

    current_index = 0
    current_track = queue[current_index]

    title = current_track["title"]
    stream_url = current_track["url"]

    threading.Thread(target=safe_play, args=(stream_url,), daemon=True).start()
    # --- Main Loop State ---
    volume = 50
    total_sec = None
    mute = False
    spinner = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    spin = 0

    while True:
        # 1. Handle Input
        key = stdscr.getch()
        if key == ord("q"):
            player.stop_stream()
            break
        elif key == ord("n"):  # Next track
            if current_index + 1 < len(queue):
                current_index += 1
                player.stop_stream()

                current_track = queue[current_index]
                title = current_track["title"]
                stream_url = current_track["url"]

                threading.Thread(
                    target=safe_play,
                    args=(stream_url,),
                    daemon=True
                ).start()

        elif key == ord("b"):  # Previous track
            if current_index > 0:
                current_index -= 1
                player.stop_stream()

                current_track = queue[current_index]
                title = current_track["title"]
                stream_url = current_track["url"]

                threading.Thread(
                    target=safe_play,
                    args=(stream_url,),
                    daemon=True
                ).start()
        elif key == ord("p"):
            player.pause_stream()
        elif key == ord("r"):
            player.resume_stream()
        elif key == ord("m"):
            player.toggle_mute()
            mute = not mute
        elif key == curses.KEY_UP:
            volume = min(100, volume + 5)
            player.set_volume(volume)
        elif key == curses.KEY_DOWN:
            volume = max(0, volume - 5)
            player.set_volume(volume)
        elif key == curses.KEY_RIGHT:
            player.seek(5)
        elif key == curses.KEY_LEFT:
            player.seek(-5)

        # 2. Redraw Components
        draw_header(header_win, banner_text, width)

        # 3. Update Player Data
        if not player.is_running():
            if current_index + 1 < len(queue):
                current_index += 1
                current_track = queue[current_index]
                title = current_track["title"]
                stream_url = current_track["url"]
                threading.Thread(target=safe_play, args=(stream_url,), daemon=True).start()
                continue
            else:
                # End of playlist
                player_win.erase()
                player_win.box()
                player_win.addstr(p_h//2, (p_w-20)//2, "Playlist finished.", curses.color_pair(4))
                player_win.refresh()
                curses.napms(1000)
                break
        elapsed = player.get_position()
        dur = player.get_duration()
        if dur and dur > 0: total_sec = dur
        
        curr_vol = player.get_volume()
        if isinstance(curr_vol, (int, float)):
            volume = int(curr_vol)

        # 4. Draw Player Window
        player_win.erase()
        player_win.box()
        player_win.addstr(0, 2, " NOW PLAYING ", curses.A_BOLD)
        
        # Display Title (truncated)
        clean_title = title[:p_w - 10]
        player_win.addstr(2, 4, f"󰎈 {clean_title}", curses.color_pair(2) | curses.A_BOLD)

        # Volume & Mute Status
        vol_str = f"VOL: {volume}%" if not mute else "VOL: MUTED"
        player_win.addstr(4, 4, vol_str, curses.color_pair(2) if not mute else curses.color_pair(4))

        # Time Info
        if elapsed is not None and total_sec:
            mins_e, secs_e = divmod(int(elapsed), 60)
            mins_t, secs_t = divmod(int(total_sec), 60)
            time_str = f"{mins_e:02}:{secs_e:02} / {mins_t:02}:{secs_t:02}"
            player_win.addstr(4, p_w - len(time_str) - 4, time_str)

            # Progress Bar
            progress = min(1.0, elapsed / total_sec)
            draw_progress_bar(player_win, 6, 4, p_w - 8, progress)
        else:
            player_win.addstr(6, 4, f"{spinner[spin%10]} Buffering content...", curses.A_DIM)
            spin += 1

        player_win.refresh()

        # 5. Draw Footer
        footer_win.erase()
        help_text = "[Q]uit  [P]ause  [R]esume  [M]ute  [↑/↓] Vol  [←/→] Seek"
        fx = max(0, (width - len(help_text)) // 2)
        footer_win.addstr(0, fx, help_text, curses.A_DIM)
        footer_win.refresh()

        curses.napms(100)

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except Exception as e:
        logging.exception(f"UI Crashed: {e}")