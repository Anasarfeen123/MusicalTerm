import subprocess
def video_stream_url(url,music_source="yt"):
    if music_source.lower() == "yt":
        video_url = url
        stream_url = subprocess.check_output(["yt-dlp", "-f", "bestaudio", "-g", video_url]).decode().strip()
        return stream_url

if __name__ == "__main__":
    stream_url = video_stream_url("https://music.youtube.com/watch?v=BbvRjLPCzJk")

    if stream_url:
        subprocess.run(["mpv", "--no-video", stream_url])
