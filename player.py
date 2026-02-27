import subprocess
import socket
import json
import os
import time

MPV_SOCKET = f"/tmp/mpvsocket_{os.getpid()}"
_mpv_process = None
_ipc_socket = None

def _connect_ipc():
    global _ipc_socket

    _ipc_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    _ipc_socket.connect(MPV_SOCKET)

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
            try:
                _connect_ipc()
                return
            except OSError:
                time.sleep(0.1)
        else:
            time.sleep(0.1)

    raise RuntimeError("mpv IPC socket not created")

def _send_command(command):
    global _ipc_socket

    if _ipc_socket is None:
        return None

    try:
        _ipc_socket.send(json.dumps(command).encode() + b"\n")

        response = b""
        while not response.endswith(b"\n"):
            chunk = _ipc_socket.recv(4096)
            if not chunk:
                return None
            response += chunk

        return json.loads(response.decode().strip())

    except (BrokenPipeError, OSError, json.JSONDecodeError):
        return None

def pause_stream():
    _send_command({"command": ["set_property", "pause", True]})


def resume_stream():
    _send_command({"command": ["set_property", "pause", False]})


def stop_stream():
    global _ipc_socket, _mpv_process

    try:
        _send_command({"command": ["quit"]})
    except:
        pass

    if _ipc_socket:
        try:
            _ipc_socket.close()
        except:
            pass
        _ipc_socket = None

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