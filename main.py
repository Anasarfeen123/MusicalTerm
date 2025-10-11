import subprocess

video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
stream_url = subprocess.check_output(
    ["yt-dlp", "-f", "bestaudio", "-g", video_url]
).decode().strip()

subprocess.run(["mpv", "--no-video", stream_url])
