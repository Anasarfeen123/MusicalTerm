import curses
from pyfiglet import Figlet
import player, core
import threading
import time

f = Figlet(font='future')
def draw_progress_bar(win, y, x, width, progress):
    bar_length = int(progress * width)
    bar = "█" * bar_length + "-" * (width - bar_length)
    win.addstr(y, x, f"[{bar}] {int(progress*100):3d}%")
    win.refresh()

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
    Main_scr.clear()
    Main_scr.addstr(1, 1, "Loading track info...", curses.color_pair(1))
    Main_scr.refresh()
    
    url = "https://music.youtube.com/watch?v=BbvRjLPCzJk"
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

    # Parse duration (format "mm:ss" or "hh:mm:ss")
    parts = [int(x) for x in duration.split(':')]
    if len(parts) == 3:
        total_seconds = parts[0]*3600 + parts[1]*60 + parts[2]
    elif len(parts) == 2:
        total_seconds = parts[0]*60 + parts[1]
    else:
        total_seconds = parts[0]

    # Start playback thread
    if isinstance(stream_url, str):
        threading.Thread(
            target=player.play_stream,
            args=(stream_url,),
            daemon=True
        ).start()
    else:
        Main_scr.addstr(5, 1, "Invalid stream URL.", curses.color_pair(1))
        Main_scr.refresh()
        stdscr.getch()
        return

    # Progress variables
    start_time = time.time()
    bar_width = width - 20 

    # Main loop
    try:
        while True:
            elapsed = time.time() - start_time
            progress = min(elapsed / total_seconds, 1.0)
            mins, secs = divmod(int(elapsed), 60)
            Main_scr.addstr(5, 1, f"Elapsed: {mins:02}:{secs:02} / {duration}")
            draw_progress_bar(Main_scr, 6, 1, bar_width, progress)
            Main_scr.refresh()

            key = stdscr.getch()
            if key == ord('q'):
                player.stop_stream()
                break
            elif key == ord('p'):
                player.pause_stream()
            elif key == ord('r'):
                player.resume_stream()

            if progress >= 1.0:
                break
            curses.napms(200)

    except KeyboardInterrupt:
        player.stop_stream()

if __name__ == '__main__':
    curses.wrapper(main)