import yt_dlp
from typing import Dict, Any

URLS = ['https://www.youtube.com/watch?v=iSFDlT43bxw']
ydl_opts: Dict[str, Any] = {
    'format': 'm4a/bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'm4a',
    }]
}


with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    error_code = ydl.download(URLS)