"""Image preparation and texture loading (GTK side)."""

from __future__ import annotations

import base64
from collections import OrderedDict

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib  # noqa: E402

KEEP_AS_IS = {"image/gif", "image/svg+xml"}   # re-encoding would flatten animation / rasterise vectors


def sniff_mime(data: bytes, filename: str = "") -> str:
    ctype, _uncertain = Gio.content_type_guess(filename or None, data[:4096])
    mime = Gio.content_type_get_mime_type(ctype) or ""
    return mime


def prepare_image(data: bytes, filename: str = "", max_dim: int = 1600) -> tuple[bytes, str]:
    """Validate an image and shrink large photos. Returns (bytes, mime).

    Whichever is smaller — the original or the re-encoded copy — is kept.
    Raises ValueError for anything that isn't a decodable image.
    """
    mime = sniff_mime(data, filename)
    if not mime.startswith("image/"):
        raise ValueError("not an image")
    if mime in KEEP_AS_IS:
        return data, mime
    try:
        loader = GdkPixbuf.PixbufLoader()
        loader.write(data)
        loader.close()
        pb = loader.get_pixbuf()
    except GLib.Error as err:
        raise ValueError("could not read this image") from err
    if pb is None:
        raise ValueError("could not read this image")
    pb = pb.apply_embedded_orientation() or pb
    w, h = pb.get_width(), pb.get_height()
    scale = min(1.0, max_dim / max(w, h))
    if scale == 1.0 and len(data) < 800 * 1024:
        return data, mime
    if scale < 1.0:
        pb = pb.scale_simple(max(1, round(w * scale)), max(1, round(h * scale)), GdkPixbuf.InterpType.HYPER)
    try:
        if pb.get_has_alpha():
            ok, buf = pb.save_to_bufferv("png", [], [])
            out_mime = "image/png"
        else:
            ok, buf = pb.save_to_bufferv("jpeg", ["quality"], ["86"])
            out_mime = "image/jpeg"
    except GLib.Error:
        return data, mime
    if ok and len(buf) < len(data):
        return bytes(buf), out_mime
    return data, mime


def data_uri(mime: str, data: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def texture_from_bytes(data: bytes) -> Gdk.Texture | None:
    gbytes = GLib.Bytes.new(data)
    try:
        return Gdk.Texture.new_from_bytes(gbytes)
    except GLib.Error:
        pass
    try:   # WebP / GIF / SVG go through gdk-pixbuf loaders
        loader = GdkPixbuf.PixbufLoader()
        loader.write(data)
        loader.close()
        pb = loader.get_pixbuf()
        return Gdk.Texture.new_for_pixbuf(pb) if pb else None
    except GLib.Error:
        return None


class TextureCache:
    """Small LRU of decoded covers so the library grid doesn't re-decode."""

    def __init__(self, store, size: int = 128):
        self.store = store
        self.size = size
        self._items: OrderedDict[str, Gdk.Texture | None] = OrderedDict()

    def get(self, image_id: str | None) -> Gdk.Texture | None:
        if not image_id:
            return None
        if image_id in self._items:
            self._items.move_to_end(image_id)
            return self._items[image_id]
        img = self.store.get_image(image_id)
        tex = texture_from_bytes(img[1]) if img else None
        self._items[image_id] = tex
        if len(self._items) > self.size:
            self._items.popitem(last=False)
        return tex
