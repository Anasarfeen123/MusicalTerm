import curses
from pyfiglet import Figlet
import player, core
import threading

f = Figlet(font='future')

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

    if result and all(x is not None for x in result):
        title, duration, stream_url = result
        Main_scr.addstr(1, 1, f"Now playing: {title}  ({duration})")
        Main_scr.addstr(3, 1, "[Q] Quit  [P] Pause  [R] Resume")
        Main_scr.refresh()

        # start playback in background
        if isinstance(stream_url, str):
            threading.Thread(
                target=player.play_stream,
                args=(stream_url,),
                daemon=True).start()
        else:
            Main_scr.addstr(5, 1, "Invalid stream URL.", curses.color_pair(1))
            Main_scr.refresh()
            return

    else:
        Main_scr.addstr(5, 1, "Failed to get music info.")
        stdscr.refresh()
        Main_scr.refresh()
    
    # loop for user keypresses
    try:
        while True:
            key = stdscr.getch()
            if key == ord('q'):
                player.stop_stream()
                break
            elif key == ord('p'):
                player.pause_stream()
                Main_scr.addstr(5, 1, "Paused... Press R to resume.  ")
                Main_scr.refresh()
            elif key == ord('r'):
                player.resume_stream()
                Main_scr.addstr(5, 1, "Resumed playback.            ")
                Main_scr.refresh()
            curses.napms(100)  # avoids 100% CPU usage
    except KeyboardInterrupt:
        player.stop_stream()
    finally:
        player.stop_stream()

if __name__ == '__main__':
    curses.wrapper(main)