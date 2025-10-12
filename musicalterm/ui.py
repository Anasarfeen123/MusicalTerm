import curses
from pyfiglet import Figlet # type: ignore

f = Figlet(font='future')

def main(stdscr):
    curses.start_color()
    curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    Main_scr = curses.newwin(height, width, 8, 0)
    Main_scr.clear()
    stdscr.addstr(f.renderText('Musical term'), curses.color_pair(1))

    Main_scr.addstr(8, 1, "Press any key to exit.")
    stdscr.refresh()
    Main_scr.refresh()
    stdscr.getch()

if __name__ == '__main__':
    curses.wrapper(main)