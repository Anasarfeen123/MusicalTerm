import subprocess
import socket
import json
import os
import time
import core

MPV_SOCKET = f"/tmp/mpvsocket_{os.getpid()}"

_mpv_process = None
_ipc_socket  = None
_muted       = False


# ─── IPC ──────────────────────────────────────────────────────────────────────

def _connect_ipc(retries=50, delay=0.1):
    global _ipc_socket
    for _ in range(retries):
        if os.path.exists(MPV_SOCKET):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect(MPV_SOCKET)
                _ipc_socket = s
                return True
            except OSError:
                pass
        time.sleep(delay)
    return False


def _send_command(command):
    global _ipc_socket

    if _ipc_socket is None:
        return None

    try:
        payload = json.dumps(command).encode() + b"\n"
        _ipc_socket.send(payload)

        response = b""
        while True:
            chunk = _ipc_socket.recv(4096)
            if not chunk:
                return None
            response += chunk
            if response.endswith(b"\n"):
                break

        data = json.loads(response.decode().strip())
        if "data" in data or data.get("error") == "success":
            return data

    except (OSError, json.JSONDecodeError, BrokenPipeError):
        _ipc_socket = None   # socket died; mark for reconnect

    return None


def _ensure_connected():
    """Attempt to reconnect IPC if socket dropped."""
    global _ipc_socket
    if _ipc_socket is None and _mpv_process and _mpv_process.poll() is None:
        _connect_ipc(retries=5, delay=0.05)


# ─── Playback ─────────────────────────────────────────────────────────────────

def play_stream(url):
    global _mpv_process, _ipc_socket

    resolved = core.resolve_stream(url)
    if not resolved:
        raise RuntimeError("Stream resolution failed")

    title, duration, stream_url = resolved
    stream_url = stream_url or url

    # Hot-swap track if mpv is already alive
    if _mpv_process and _mpv_process.poll() is None:
        _ensure_connected()
        if _ipc_socket:
            res = _send_command({"command": ["loadfile", stream_url, "replace"]})
            if res is not None:
                return
        stop_stream()

    # Fresh mpv process
    if os.path.exists(MPV_SOCKET):
        os.remove(MPV_SOCKET)

    cmd = [
        "mpv",
        "--no-video",
        "--no-terminal",
        "--really-quiet",
        f"--input-ipc-server={MPV_SOCKET}",
        "--msg-level=all=no",
        "--volume=70",
        stream_url,
    ]

    _mpv_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )

    if not _connect_ipc():
        raise RuntimeError("mpv IPC socket not created in time")


def stop_stream():
    global _ipc_socket, _mpv_process

    try:
        _send_command({"command": ["quit"]})
    except Exception:
        pass

    if _ipc_socket:
        try:
            _ipc_socket.close()
        except Exception:
            pass
        _ipc_socket = None

    if _mpv_process:
        try:
            _mpv_process.terminate()
            _mpv_process.wait(timeout=3)
        except Exception:
            try:
                _mpv_process.kill()
            except Exception:
                pass
    _mpv_process = None


def is_running():
    return _mpv_process is not None and _mpv_process.poll() is None


# ─── Controls ─────────────────────────────────────────────────────────────────

def pause_stream():
    _ensure_connected()
    _send_command({"command": ["set_property", "pause", True]})


def resume_stream():
    _ensure_connected()
    _send_command({"command": ["set_property", "pause", False]})


def seek(seconds):
    _ensure_connected()
    _send_command({"command": ["seek", seconds, "relative"]})


def set_volume(value):
    _ensure_connected()
    value = max(0, min(150, int(value)))
    _send_command({"command": ["set_property", "volume", value]})


def toggle_mute():
    global _muted
    _ensure_connected()
    _muted = not _muted
    _send_command({"command": ["set_property", "mute", _muted]})


# ─── Info ─────────────────────────────────────────────────────────────────────

def _get(prop):
    _ensure_connected()
    res = _send_command({"command": ["get_property", prop]})
    return res["data"] if res and "data" in res else None


def get_position():  return _get("time-pos")
def get_duration():  return _get("duration")
def get_volume():    return _get("volume")
def is_muted():      return _muted