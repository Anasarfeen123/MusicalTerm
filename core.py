import yt_dlp

def extract_media(url):
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # Playlist detected
            if "entries" in info and info["entries"]:
                tracks = []
                for entry in info["entries"]:
                    if not entry:
                        continue
                    tracks.append({
                        "title": entry.get("title"),
                        "url": entry.get("url"),
                    })

                return {
                    "type": "playlist",
                    "tracks": tracks,
                    "title": info.get("title")
                }

            # Single video
            return {
                "type": "video",
                "tracks": [{
                    "title": info.get("title"),
                    "url": info.get("url"),
                }]
            }

    except Exception:
        return None

def video_info(url):
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            stream_url = info.get("url")
            title = info.get("fulltitle")
            duration = info.get("duration_string")

            return title, duration, stream_url

    except Exception:
        return None