import os
import contextlib
import yt_dlp
import requests
from PIL import Image

os.environ["YTDLP_REMOTE_COMPONENTS"] = "ejs:github"

# ─── URL Normalization ────────────────────────────────────────────────────────

def normalize_youtube_url(url):
    if "music.youtube.com" in url:
        url = url.replace("music.youtube.com", "www.youtube.com")
    return url


# ─── Shared ydl opts ─────────────────────────────────────────────────────────

_BASE_OPTS = {
    "quiet":       True,
    "no_warnings": True,
    "noplaylist":  True,
    "remote_components": "ejs:github",
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


# ─── Stream Resolution ────────────────────────────────────────────────────────

def resolve_stream(url):
    url  = normalize_youtube_url(url)
    opts = {
        **_BASE_OPTS,
        "format":              "bestaudio/best",
        "extract_flat":        False,
        "allow_unplayable_formats": True,
    }

    try:
        with open(os.devnull, "w") as devnull:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)

        return info.get("title"), info.get("duration"), info.get("url")
    except Exception:
        return None


# ─── Playlist / Single Extraction ────────────────────────────────────────────

def extract_media(url):
    """
    Returns:
        {type: "video"|"playlist", title: str, tracks: [{title, url}]}
    """
    url  = normalize_youtube_url(url)
    opts = {**_BASE_OPTS, "skip_download": True, "extract_flat": True}

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if "entries" in info and info["entries"]:
            tracks = [
                {
                    "title": e.get("title") or "Unknown",
                    "url":   e.get("url") or e.get("webpage_url"),
                }
                for e in info["entries"] if e
            ]
            return {"type": "playlist", "title": info.get("title"), "tracks": tracks}

        return {
            "type":   "video",
            "title":  info.get("title"),
            "tracks": [{"title": info.get("title"), "url": url}],
        }

    except Exception as e:
        print("extract_media error:", e)
        return None


# ─── Thumbnail Download ───────────────────────────────────────────────────────

def download_thumbnail(url, save_path="cover.jpg"):
    url  = normalize_youtube_url(url)
    opts = {**_BASE_OPTS, "skip_download": True, "extract_flat": False}

    try:
        with open(os.devnull, "w") as devnull:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info          = ydl.extract_info(url, download=False)
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


def get_dominant_color(path):
    try:
        im = Image.open(path).convert("RGB")
        im = im.resize((50, 50)) # Resize small for speed
        pixels = list(im.getdata())
        
        # Simple frequency count, ignoring very dark/very light pixels
        counts = {}
        for r, g, b in pixels:
            if 30 < (r + g + b) < 700: # Skip near-black and near-white
                rgb = (r, g, b)
                counts[rgb] = counts.get(rgb, 0) + 1
        
        if not counts: return (214, 214, 214) # Fallback to gold-ish
        return max(counts, key=counts.get)
    except:
        return (214, 214, 214)

# ─── Image → Pixel Matrix ────────────────────────────────────────────────────

def get_album_art_matrix(path, size=30):
    try:
        if not os.path.exists(path):
            return None, 0, 0

        im = Image.open(path).convert("RGB")
        # For High-Def Half-Blocks, we want a 1:1 pixel aspect ratio 
        # before the terminal stretches it.
        new_width = size
        new_height = size
        
        im = im.resize((new_width, new_height), Image.Resampling.LANCZOS)
        dom_color = get_dominant_color(path)
        return list(im.getdata()), new_width, im.height, dom_color
    except Exception:
        return None, 0, 0