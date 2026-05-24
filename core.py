import os
import contextlib
from typing import Any, Dict, cast
import yt_dlp
import requests
from PIL import Image

os.environ["YTDLP_REMOTE_COMPONENTS"] = "ejs:github"

# ─── URL Normalization ────────────────────────────────────────────────────────

def normalize_youtube_url(url):
    if "music.youtube.com" in url:
        url = url.replace("music.youtube.com", "www.youtube.com")
    return url


def is_probable_url(value):
    value = (value or "").strip().lower()
    return value.startswith(("http://", "https://")) or "youtube.com/" in value or "youtu.be/" in value


def media_query(value):
    """
    Accept either a YouTube URL or a plain search query.
    Plain queries use yt-dlp's YouTube search extractor.
    """
    value = (value or "").strip()
    if is_probable_url(value):
        return normalize_youtube_url(value)
    return f"ytsearch12:{value}"


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
    source = media_query(url)
    url  = normalize_youtube_url(source)
    opts = {**_BASE_OPTS, "skip_download": True, "extract_flat": True, "noplaylist": False}

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if "entries" in info and info["entries"]:
            tracks = [
                {
                    "title": e.get("title") or "Unknown",
                    "url":   e.get("webpage_url") or e.get("url"),
                    "duration": e.get("duration"),
                    "uploader": e.get("uploader") or e.get("channel"),
                }
                for e in info["entries"] if e
            ]
            media_type = "search" if source.startswith("ytsearch") else "playlist"
            return {"type": media_type, "title": info.get("title") or url, "tracks": tracks}

        return {
            "type":   "video",
            "title":  info.get("title"),
            "tracks": [{
                "title": info.get("title"),
                "url": url,
                "duration": info.get("duration"),
                "uploader": info.get("uploader") or info.get("channel"),
            }],
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
        im.thumbnail((100, 100))
        pixels = list(im.getdata())
        
        counts = {}
        for r, g, b in pixels:
            # Boost saturation for dominant color detection
            if 40 < (r + g + b) < 700:
                rgb = (r, g, b)
                counts[rgb] = counts.get(rgb, 0) + 1
        
        if not counts: return (214, 214, 214)
        return max(counts, key=counts.get)
    except:
        return (214, 214, 214)

# ─── Image → Pixel Matrix ────────────────────────────────────────────────────

def get_album_art_matrix(path, max_w=40, max_h=20):
    """
    Returns a pixel matrix optimized for terminal half-blocks.
    Half-blocks are 1 char wide and 0.5 char high.
    To get a square image in terminal, we need width = 2 * height (in pixels).
    Wait, no. Terminal characters are roughly 2:1 height:width.
    So 1 character wide, 1 character high (2 half-blocks) is roughly square.
    Thus, width_px = height_px results in a square image.
    """
    try:
        if not os.path.exists(path):
            return None, 0, 0, (214, 214, 214)

        im = Image.open(path).convert("RGB")
        
        # Target dimensions for the half-block renderer
        # max_w is characters, max_h is characters.
        # Each character is 1px wide and 2px high in the pixel matrix.
        target_w = max_w
        target_h = max_h * 2
        
        # Maintain aspect ratio
        im.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        
        dom_color = get_dominant_color(path)
        return list(im.getdata()), im.width, im.height, dom_color
    except Exception:
        return None, 0, 0, (214, 214, 214)
