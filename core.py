import yt_dlp
import subprocess

def video_info(url, music_source="yt"):
    if music_source.lower() != "yt":
        raise ValueError("Unsupported music source")

    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: # type: ignore
            info = ydl.extract_info(url, download=False)
            stream_url = info.get('url')
            fulltitle = info.get('fulltitle')
            duration_string = info.get('duration_string')
            x = (fulltitle, duration_string, stream_url)
            return x
    except Exception as e:
        print(f"Error: Failed to retrieve info.\nReason: {e}")
        return None

if __name__ == "__main__":
    url = "https://music.youtube.com/watch?v=BbvRjLPCzJk"
    result = video_info(url)
    
    if result and all(x is not None for x in result):
        title, duration, stream_url = result
        print(f"Now playing: {title}  ({duration})")
        if isinstance(stream_url, str):
            subprocess.run(["mpv", "--no-video", stream_url])
        else:
            print("Invalid stream URL.")
            exit(1)
    else:
        print("Failed to music info.")
        exit(1)