import subprocess
import socket
import json
import os
import time

MPV_SOCKET = f"/tmp/mpvsocket_{os.getpid()}"
_mpv_process = None

def play_stream(url):
    global _mpv_process

    # If an old instance exists, kill it first
    if _mpv_process and _mpv_process.poll() is None:
        try:
            _mpv_process.terminate()
            _mpv_process.wait(timeout=2)
        except:
            _mpv_process.kill()

    # Remove old socket if it exists
    if os.path.exists(MPV_SOCKET):
        os.remove(MPV_SOCKET)

    cmd = [
        "mpv",
        "--no-video",
        "--really-quiet",
        "--no-terminal",
        f"--input-ipc-server={MPV_SOCKET}",
        url
    ]

    _mpv_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    for _ in range(30):
        if os.path.exists(MPV_SOCKET):
            return
        time.sleep(0.1)

    raise RuntimeError("mpv IPC socket not created")

def _send_command(command):
    if not os.path.exists(MPV_SOCKET):
        return None

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(MPV_SOCKET)
            sock.send(json.dumps(command).encode() + b"\n")
            response = sock.recv(4096)
            return json.loads(response)
    except (ConnectionRefusedError, FileNotFoundError, BrokenPipeError):
        return None


def pause_stream():
    _send_command({"command": ["set_property", "pause", True]})


def resume_stream():
    _send_command({"command": ["set_property", "pause", False]})


def stop_stream():
    global _mpv_process

    try:
        _send_command({"command": ["quit"]})
    except:
        pass

    if _mpv_process and _mpv_process.poll() is None:
        _mpv_process.terminate()
        _mpv_process.wait()

    _mpv_process = None

def is_running():
    global _mpv_process
    return _mpv_process and _mpv_process.poll() is None

def get_position():
    res = _send_command({"command": ["get_property", "time-pos"]})
    if res and "data" in res:
        return res["data"]
    return None


def get_duration():
    res = _send_command({"command": ["get_property", "duration"]})
    if res and "data" in res:
        return res["data"]
    return None

def seek(seconds):
    _send_command({"command": ["seek", seconds, "relative"]})

def set_volume(value):
    _send_command({"command": ["set_property", "volume", value]})

def toggle_mute():
    _send_command({"command": ["cycle", "mute"]})

def is_muted():
    res = _send_command({"command": ["get_property", "mute"]})
    return res["data"] if res and "data" in res else False

def get_volume():
    res = _send_command({"command": ["get_property", "volume"]})
    return res["data"] if res and "data" in res else None