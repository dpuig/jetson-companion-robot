#!/usr/bin/env python3
"""Fullscreen WebKit window for the robot face, for use inside the Ubuntu desktop (no sudo needed).

Runs ON the Jetson:  DISPLAY=:0 python3 scripts/face-viewer.py URL
Escape closes it. Robot mode runs this same viewer as the kiosk, on a bare X server with no window
manager (see scripts/jetson-robot-mode.sh). On the desktop it also inhibits GNOME's idle
blanking/lock while open (like a video player does); the user's settings are untouched.
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.0")
from gi.repository import Gdk, Gio, Gtk, WebKit2  # noqa: E402


def on_activate(app, url):
    win = Gtk.ApplicationWindow(application=app, title="Companion Face")
    view = WebKit2.WebView()
    settings = view.get_settings()
    settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)
    settings.set_enable_write_console_messages_to_stdout(True)  # page errors land in the log
    win.add(view)
    # Without a window manager (robot-mode kiosk) fullscreen() is a no-op, so size it ourselves.
    screen = Gdk.Screen.get_default()
    win.set_decorated(False)
    win.set_default_size(screen.get_width(), screen.get_height())
    win.move(0, 0)
    win.connect("key-press-event", lambda _w, e: app.quit() if e.keyval == Gdk.KEY_Escape else False)
    win.connect("realize", lambda w: w.get_window().set_cursor(
        Gdk.Cursor.new_from_name(w.get_display(), "none")))
    view.load_uri(url)
    win.fullscreen()
    win.show_all()
    app.inhibit(win, Gtk.ApplicationInhibitFlags.IDLE, "Showing the robot face")


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080/face"
    app = Gtk.Application(application_id="local.companion.FaceViewer", flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", on_activate, url)
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()
