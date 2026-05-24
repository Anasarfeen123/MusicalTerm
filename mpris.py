import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import threading
import os

class MPRISPlayer(dbus.service.Object):
    def __init__(self, name, player_module):
        self.player = player_module
        self._metadata = dbus.Dictionary({}, signature='sv')
        self._status = "Stopped"
        
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SessionBus()
        self.bus_name = dbus.service.BusName(f"org.mpris.MediaPlayer2.{name}", self.bus)
        super().__init__(self.bus, "/org/mpris/MediaPlayer2")

    def update_metadata(self, track_info):
        m = {}
        if track_info.get("title"):
            m["xesam:title"] = dbus.String(track_info["title"])
        if track_info.get("uploader"):
            m["xesam:artist"] = dbus.Array([dbus.String(track_info["uploader"])], signature="s")
        
        duration = track_info.get("duration")
        if duration is not None:
            try:
                m["mpris:length"] = dbus.Int64(int(duration) * 1000000)
            except:
                pass
        
        m["mpris:trackid"] = dbus.String("/org/mpris/MediaPlayer2/Track/0")
            
        self._metadata = dbus.Dictionary(m, signature='sv')
        self.PropertiesChanged("org.mpris.MediaPlayer2.Player", 
                              dbus.Dictionary({"Metadata": self._metadata}, signature='sv'), 
                              dbus.Array([], signature='s'))

    def update_status(self, status):
        self._status = status
        self.PropertiesChanged("org.mpris.MediaPlayer2.Player", 
                              dbus.Dictionary({"PlaybackStatus": dbus.String(status)}, signature='sv'), 
                              dbus.Array([], signature='s'))

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed_properties, invalidated_properties):
        pass

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface_name, property_name):
        return self.GetAll(interface_name)[property_name]

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface_name):
        if interface_name == "org.mpris.MediaPlayer2":
            return dbus.Dictionary({
                "CanQuit": dbus.Boolean(True),
                "Identity": dbus.String("MusicalTerm"),
                "SupportedUriSchemes": dbus.Array(["http", "https", "file"], signature="s"),
                "SupportedMimeTypes": dbus.Array(["audio/mpeg", "audio/ogg"], signature="s"),
                "CanRaise": dbus.Boolean(False),
                "HasTrackList": dbus.Boolean(False),
            }, signature='sv')
        elif interface_name == "org.mpris.MediaPlayer2.Player":
            pos = self.player.get_position()
            return dbus.Dictionary({
                "PlaybackStatus": dbus.String(self._status),
                "Metadata": self._metadata,
                "Position": dbus.Int64(int((pos or 0) * 1000000)),
                "CanGoNext": dbus.Boolean(True),
                "CanGoPrevious": dbus.Boolean(True),
                "CanPlay": dbus.Boolean(True),
                "CanPause": dbus.Boolean(True),
                "CanSeek": dbus.Boolean(True),
                "CanControl": dbus.Boolean(True),
                "Volume": dbus.Double(1.0),
            }, signature='sv')
        return dbus.Dictionary({}, signature='sv')

    @dbus.service.method("org.mpris.MediaPlayer2")
    def Raise(self): pass

    @dbus.service.method("org.mpris.MediaPlayer2")
    def Quit(self): self.player.stop_stream()

    @dbus.service.method("org.mpris.MediaPlayer2.Player")
    def Next(self): 
        if hasattr(self.player, "on_next"): self.player.on_next()

    @dbus.service.method("org.mpris.MediaPlayer2.Player")
    def Previous(self):
        if hasattr(self.player, "on_prev"): self.player.on_prev()

    @dbus.service.method("org.mpris.MediaPlayer2.Player")
    def Pause(self): self.player.pause_stream()

    @dbus.service.method("org.mpris.MediaPlayer2.Player")
    def Play(self): self.player.resume_stream()

    @dbus.service.method("org.mpris.MediaPlayer2.Player")
    def Stop(self): self.player.stop_stream()

    @dbus.service.method("org.mpris.MediaPlayer2.Player")
    def PlayPause(self):
        if self._status == "Playing": self.player.pause_stream()
        else: self.player.resume_stream()

    @dbus.service.method("org.mpris.MediaPlayer2.Player", signature="x")
    def Seek(self, Offset): self.player.seek(Offset / 1000000.0)

    @dbus.service.method("org.mpris.MediaPlayer2.Player", signature="ox")
    def SetPosition(self, TrackId, Position): pass

    @dbus.service.method("org.mpris.MediaPlayer2.Player", signature="s")
    def OpenUri(self, Uri): pass

_mpris_obj = None

def start_mpris(player_module):
    global _mpris_obj
    try:
        _mpris_obj = MPRISPlayer("MusicalTerm", player_module)
        loop = GLib.MainLoop()
        t = threading.Thread(target=loop.run, daemon=True)
        t.start()
    except Exception:
        _mpris_obj = None

def update_mpris_metadata(track_info):
    if _mpris_obj: _mpris_obj.update_metadata(track_info)

def update_mpris_status(status):
    if _mpris_obj: _mpris_obj.update_status(status)
