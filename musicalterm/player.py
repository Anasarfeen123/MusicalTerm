import subprocess
import core


def play_stream(url):
    """Blocking: spawns ffplay to play the provided stream URL.

    This function is intended to be run in a background thread.
    """
    cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", url]
    subprocess.run(cmd)


def pause_stream():
    """Pause ffplay by sending SIGSTOP to the process."""
    cmd = ["pkill", "-STOP", "ffplay"]
    subprocess.run(cmd)


def resume_stream():
    """Resume ffplay by sending SIGCONT to the process."""
    cmd = ["pkill", "-CONT", "ffplay"]
    subprocess.run(cmd)


def stop_stream():
    """Stop/kill the ffplay process."""
    cmd = ["pkill", "-TERM", "ffplay"]
    subprocess.run(cmd)

if __name__ == "__main__":
    url = "https://music.youtube.com/watch?v=BbvRjLPCzJk"
    result = core.video_info(url)
    
    if result and all(x is not None for x in result):
        title, duration, stream_url = result
        print(f"Now playing: {title}  ({duration})")
        if isinstance(stream_url, str):
            play_stream(stream_url)
        else:
            print("Invalid stream URL.")
            exit(1)
    else:
        print("Failed to music info.")
        exit(1)