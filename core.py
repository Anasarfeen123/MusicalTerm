import os
import yt_dlp
import requests
from PIL import Image
import contextlib
import sys
import os
os.environ["YTDLP_REMOTE_COMPONENTS"] = "ejs:github"
def normalize_youtube_url(url):
    if "music.youtube.com" in url:
        url = url.replace("music.youtube.com", "www.youtube.com")
    return url


# -----------------------------
# STREAM RESOLUTION
# -----------------------------

def resolve_stream(url):
    url = normalize_youtube_url(url)
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "noplaylist": True,
        "ignoreerrors": True,
        "remote_components": "ejs:github",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "allow_unplayable_formats": True,
    }


    try:
        with open(os.devnull, "w") as devnull:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)

        title = info.get("title")
        duration = info.get("duration")
        stream_url = info.get("url")

        return title, duration, stream_url

    except Exception:
        return None

# -----------------------------
# PLAYLIST / MEDIA EXTRACTION
# -----------------------------

def extract_media(url):
    """
    Returns:
    {
        type: "video" | "playlist",
        title: str,
        tracks: [ { title, url } ]
    }
    """
    url = normalize_youtube_url(url)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "remote_components": "ejs:github",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # Playlist
            if "entries" in info and info["entries"]:
                tracks = []
                for entry in info["entries"]:
                    if not entry:
                        continue

                    tracks.append({
                        "title": entry.get("title"),
                        "url": entry.get("url") or entry.get("webpage_url"),
                    })

                return {
                    "type": "playlist",
                    "tracks": tracks,
                    "title": info.get("title"),
                }

            # Single video
            return {
                "type": "video",
                "tracks": [{
                    "title": info.get("title"),
                    "url": url,
                }]
            }

    except Exception as e:
        print("extract_media error:", e)
        return None


# -----------------------------
# THUMBNAIL DOWNLOAD
# -----------------------------

def download_thumbnail(url, save_path="cover.jpg"):
    url = normalize_youtube_url(url)

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": False,
    }

    try:
        with open(os.devnull, "w") as devnull:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    thumbnail_url = info.get("thumbnail")

                    if thumbnail_url:
                        resp = requests.get(thumbnail_url, stream=True, timeout=10)
                        if resp.status_code == 200:
                            with open(save_path, "wb") as f:
                                for chunk in resp.iter_content(1024):
                                    f.write(chunk)
                            return True
    except Exception:
        pass

    return False


# -----------------------------
# IMAGE → MATRIX (for curses art)
# -----------------------------

def get_album_art_matrix(path, size=30):
    try:
        if not os.path.exists(path):
            return None, 0, 0

        im = Image.open(path).convert("RGB")
        aspect_ratio = im.height / im.width
        new_width = size
        new_height = int(aspect_ratio * new_width * 1.1)

        im = im.resize(
            (new_width, max(1, new_height)),
            Image.Resampling.LANCZOS
        )

        return list(im.getdata()), new_width, im.height

    except Exception:
        return None, 0, 0