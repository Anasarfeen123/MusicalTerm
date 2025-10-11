import subprocess
import core

def play_stream(url):
    cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", url]
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