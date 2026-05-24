import os
import contextlib
from typing import Any, Dict, cast
from urllib.parse import urlencode
import re
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
    if value.startswith(("http://", "https://")):
        return True
    if any(p in value for p in ["youtube.com/", "youtu.be/", "music.youtube.com/"]):
        return True
    return False


def is_local_path(value):
    return os.path.exists(os.path.expanduser(value))


def media_query(value):
    """
    Accept either a YouTube URL, a local path, or a plain search query.
    """
    value = (value or "").strip()
    if is_probable_url(value):
        return normalize_youtube_url(value)
    if is_local_path(value):
        return os.path.expanduser(value)
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
    if is_local_path(url):
        # For local files, the URL is the path itself.
        # We can try to get metadata using yt-dlp or just return basics.
        return os.path.basename(url), None, url

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
        {type: "video"|"playlist"|"local", title: str, tracks: [{title, url}]}
    """
    source = media_query(url)
    
    if is_local_path(source):
        path = os.path.abspath(source)
        if os.path.isdir(path):
            tracks = []
            for root, _, files in os.walk(path):
                for f in sorted(files):
                    if f.lower().endswith((".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus")):
                        full_path = os.path.join(root, f)
                        tracks.append({
                            "title": f,
                            "url": full_path,
                            "duration": None,
                            "uploader": "Local File",
                        })
            return {
                "type": "playlist",
                "title": os.path.basename(path),
                "tracks": tracks
            }
        else:
            return {
                "type": "local",
                "title": os.path.basename(path),
                "tracks": [{
                    "title": os.path.basename(path),
                    "url": path,
                    "duration": None,
                    "uploader": "Local File",
                }]
            }

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
    if is_local_path(url):
        # For local files, we could try to extract embedded art, 
        # but for now let's just return False or look for cover.jpg in the same dir.
        dir_path = os.path.dirname(url)
        for name in ["cover.jpg", "cover.png", "folder.jpg", "folder.png"]:
            p = os.path.join(dir_path, name)
            if os.path.exists(p):
                import shutil
                shutil.copy(p, save_path)
                return True
        return False

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


# ─── Lyrics Extraction ────────────────────────────────────────────────────────

def fetch_lyrics(url, title=None, artist=None, duration=None):
    """
    Fetches synced lyrics (subtitles) if available.
    Returns raw subtitle text if available.
    """
    if is_local_path(url):
        # Look for .lrc file
        base = os.path.splitext(url)[0]
        for ext in [".lrc", ".srt", ".vtt"]:
            p = base + ext
            if os.path.exists(p):
                # Simple parser for now
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as f:
                        return f.read() # Return raw for now, parse in UI
                except:
                    pass
        return None

    lrc_lyrics = _fetch_lrclib_lyrics(title, artist, duration)
    if lrc_lyrics:
        return lrc_lyrics

    url = normalize_youtube_url(url)
    opts = {
        **_BASE_OPTS,
        "skip_download": True,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "subtitlesformat": "vtt/srt/json3/best",
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        sub_url = _pick_subtitle_url(
            info.get("subtitles") or {},
            info.get("automatic_captions") or {},
            info.get("requested_subtitles") or {},
        )
        if sub_url:
            resp = requests.get(sub_url, timeout=10)
            if resp.status_code == 200:
                return resp.text
    except Exception:
        pass
    return None


def _fetch_lrclib_lyrics(title=None, artist=None, duration=None):
    title, artist = _clean_lyrics_query(title, artist)
    if not title:
        return None

    params = {"track_name": title}
    if artist:
        params["artist_name"] = artist
    if duration:
        params["duration"] = int(duration)

    try:
        resp = requests.get(
            f"https://lrclib.net/api/search?{urlencode(params)}",
            headers={"User-Agent": "MusicalTerm/1.0"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        results = resp.json()
    except Exception:
        return None

    if not isinstance(results, list):
        return None

    for item in results:
        if not isinstance(item, dict):
            continue
        synced = item.get("syncedLyrics")
        if synced:
            return synced
    for item in results:
        if not isinstance(item, dict):
            continue
        plain = item.get("plainLyrics")
        if plain:
            return plain
    return None


def _clean_lyrics_query(title=None, artist=None):
    title = (title or "").strip()
    artist = (artist or "").strip()

    for sep in (" - ", " – ", " — "):
        if sep in title and not artist:
            maybe_artist, maybe_title = title.split(sep, 1)
            artist = maybe_artist.strip()
            title = maybe_title.strip()
            break

    noise = [
        "official music video",
        "official video",
        "official audio",
        "lyrics video",
        "lyric video",
        "audio",
        "video",
        "lyrics",
        "hd",
        "hq",
    ]
    for marker in noise:
        title = title.replace(f"({marker})", "")
        title = title.replace(f"[{marker}]", "")
        title = title.replace(marker.title(), "")
        title = title.replace(marker.upper(), "")

    title = re.sub(r"\(\s*\)|\[\s*\]", "", title)
    return " ".join(title.split()), " ".join(artist.split())


def _pick_subtitle_url(*subtitle_maps):
    """
    yt-dlp subtitle maps are {language: [format, ...]} for subtitles and
    automatic captions, but requested_subtitles may be {language: format}.
    Prefer English and parser-friendly formats, then fall back to anything
    with a URL.
    """
    candidates = []
    for source_priority, subtitle_map in enumerate(subtitle_maps):
        for lang, formats in subtitle_map.items():
            if isinstance(formats, dict):
                formats = [formats]
            if not isinstance(formats, list):
                continue

            lang_priority = _subtitle_lang_priority(lang)
            for fmt in formats:
                if not isinstance(fmt, dict) or not fmt.get("url"):
                    continue
                ext = (fmt.get("ext") or "").lower()
                candidates.append((
                    lang_priority,
                    source_priority,
                    _subtitle_ext_priority(ext),
                    fmt["url"],
                ))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[:3])
    return candidates[0][3]


def _subtitle_lang_priority(lang):
    lang = (lang or "").lower()
    if lang == "en":
        return 0
    if lang.startswith("en-") or lang.startswith("en_"):
        return 1
    if lang.startswith("en"):
        return 2
    return 3


def _subtitle_ext_priority(ext):
    order = {
        "vtt": 0,
        "srt": 1,
        "json3": 2,
        "srv3": 3,
        "srv2": 4,
        "srv1": 5,
        "ttml": 6,
    }
    return order.get(ext, 99)


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
