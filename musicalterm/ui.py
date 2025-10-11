import curses

def main(stdscr):
    stdscr.clear()
    stdscr.addstr(0, 0, "Hello, Curses!")
    stdscr.addstr(1, 0, "Press any key to exit.")
    stdscr.refresh()
    stdscr.getch() # Wait for a key press

if __name__ == '__main__':
    curses.wrapper(main)