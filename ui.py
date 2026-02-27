import curses
from pyfiglet import Figlet
import player, core
import threading
import logging

f = Figlet(font='future')
def draw_progress_bar(win, y, x, width, progress):
    bar_length = int(progress * width)
    bar = "#" * bar_length + "-" * (width - bar_length)
    win.addstr(y, x, f"[{bar}] {int(progress*100):3d}%")
    win.refresh()

logging.basicConfig(
    filename="musicalterm_crash.log",
    level=logging.DEBUG
)

def safe_play(url):
    try:
        player.play_stream(url)
    except Exception as e:
        logging.exception(f"Playback thread crashed: {e}")

def main(stdscr):
    curses.start_color()
    curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    stdscr.nodelay(True)  # non-blocking input
    # Main_scr = curses.newwin(height - 8, width, 8, 0)
    # Main_scr.clear()

    banner = f.renderText('MusicalTerm').splitlines()
    try:
        for i, line in enumerate(banner):
            stdscr.addstr(i, 0, line[:width-1], curses.color_pair(1))
    except curses.error:
        stdscr.addstr('\n'.join(banner))
    stdscr.refresh()
    Main_scr = curses.newwin(height - len(banner), width, len(banner), 0)
    main_h, main_w = Main_scr.getmaxyx()
    Main_scr.clear()
    Main_scr.addstr(1, 1, "Loading track info...", curses.color_pair(1))
    Main_scr.refresh()
    
    url = "https://music.youtube.com/watch?v=JRSuFghK2_0"
    result = core.video_info(url)

    if not result or not all(x is not None for x in result):
        Main_scr.addstr(5, 1, "Failed to get music info.", curses.color_pair(1))
        Main_scr.refresh()
        stdscr.getch()
        return

    title, duration, stream_url = result
    if duration is None:
        duration = "00:00"
    Main_scr.addstr(1, 1, f"Now playing: {title}  ({duration})")
    Main_scr.addstr(3, 1, "[Q] Quit  [P] Pause  [R] Resume")
    Main_scr.refresh()
    # Start playback thread
    if isinstance(stream_url, str):
        threading.Thread(
            target=safe_play,
            args=(stream_url,),
            daemon=True
        ).start()
    else:
        Main_scr.addstr(5, 1, "Invalid stream URL.", curses.color_pair(1))
        Main_scr.refresh()
        stdscr.getch()
        return
# ... inside main(stdscr) ...
    bar_width = max(10, main_w - 20)
    stdscr.keypad(True)
    volume = 50 # Default to a safe integer
    mute = False
    total = None

    try:
        while True:
            if player.is_running() is False:
                curses.napms(100)
                continue

            # 1. Update playback data
            elapsed = player.get_position()
            new_total = player.get_duration()
            if new_total and new_total > 1:
                total = new_total
            
            # Defensive volume check
            current_vol = player.get_volume()
            if current_vol is not None:
                volume = current_vol

            # 2. Process ALL pending keys
            while True:
                key = stdscr.getch()
                if key == -1: 
                    break
                
                if key == ord('q'):
                    player.stop_stream()
                    return 
                elif key == ord('p'):
                    player.pause_stream()
                elif key == ord('r'):
                    player.resume_stream()
                elif key == curses.KEY_RIGHT:
                    player.seek(5)
                elif key == curses.KEY_LEFT:
                    player.seek(-5)
                elif key == curses.KEY_UP:
                    volume = min(100, volume + 5)
                    player.set_volume(volume)
                elif key == curses.KEY_DOWN:
                    volume = max(0, volume - 5)
                    player.set_volume(volume)
                elif key == ord('m'):
                    player.toggle_mute()
                    mute = not mute

            # 3. Update UI (Added more safety checks)
            Main_scr.move(4, 1)
            Main_scr.clrtoeol()
            status = "(muted)" if mute else ""
            Main_scr.addstr(4, 1, f"Volume: {int(volume)}% {status}")
            if (
                elapsed is not None and
                total is not None and
                total > 1 and              # ignore tiny fake durations
                elapsed <= total           # prevent overflow spike
            ):
                progress = elapsed / total
            else:
                progress = None
            if progress is not None:
                mins, secs = divmod(int(elapsed), 60)
                total_m, total_s = divmod(int(total), 60)

                Main_scr.move(5, 1)
                Main_scr.clrtoeol()
                Main_scr.addstr(
                    5, 1,
                    f"Elapsed: {mins:02}:{secs:02} / {total_m:02}:{total_s:02}"
                )

                if 6 < main_h:
                    draw_progress_bar(Main_scr, 6, 1, bar_width, progress)
            else:
                Main_scr.move(5, 1)
                Main_scr.clrtoeol()
                Main_scr.addstr(5, 1, "Buffering...")
            
            Main_scr.refresh()
            curses.napms(50)
    except KeyboardInterrupt:
        player.stop_stream()
    

if __name__ == '__main__':
    try:
        curses.wrapper(main)
    except Exception as e:
        curses.endwin()
        logging.exception(f"Application crashed: {e}")
        import traceback
        print("\n--- APPLICATION CRASHED ---\n")
        traceback.print_exc()