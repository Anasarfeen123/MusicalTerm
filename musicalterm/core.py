import subprocess

def video_stream_url(url, music_source="yt"):
    try:
        if music_source.lower() == "yt":
            stream_url = subprocess.check_output(["yt-dlp", "-f", "bestaudio", "-g", url],
            stderr=subprocess.DEVNULL  # suppress yt-dlp’s noise
            ).decode().strip()
            return stream_url
        else:
            raise ValueError("Unsupported music source")
    except subprocess.CalledProcessError:
        print("Error: Failed to retrieve stream URL.")
        return None

if __name__ == "__main__":
    stream_url = video_stream_url("https://music.youtube.com/watch?v=BbvRjLPCzJk")

    if stream_url:
        subprocess.run(["mpv", "--no-video", stream_url])