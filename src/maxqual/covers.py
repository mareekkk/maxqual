"""Cover art upgrade: replace embedded art when a strictly larger image exists.

Sources the current image size from the file itself and looks up higher
resolution artwork via the public iTunes Search API, matching on album,
title and artist. Only replaces when the candidate is strictly larger.
"""

import io
import re
import time

import requests

from .tags import _jpeg

UA = {"User-Agent": "Mozilla/5.0 (maxqual)"}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def current_cover(path):
    """Return (bytes, (w, h)) of embedded art or (None, (0, 0))."""
    import base64
    from mutagen.mp4 import MP4
    from mutagen.oggopus import OggOpus
    from mutagen.flac import Picture
    from PIL import Image
    if path.endswith(".m4a"):
        c = MP4(path).get("covr")
        data = bytes(c[0]) if c else None
    else:
        a = OggOpus(path)
        mbp = (a.get("metadata_block_picture") or [None])[0]
        data = Picture(base64.b64decode(mbp)).data if mbp else None
    if not data:
        return None, (0, 0)
    im = Image.open(io.BytesIO(data))
    return data, im.size


def itunes_art(term, album, title, artist):
    try:
        r = requests.get("https://itunes.apple.com/search", params={
            "term": term, "entity": "song", "limit": 5,
        }, headers=UA, timeout=20)
        results = r.json().get("results") or []
    except (requests.RequestException, ValueError):
        return None

    def score(x):
        s = 0
        if album and _norm(x.get("collectionName", "")) == _norm(album):
            s += 4
        if _norm(x.get("trackName", "")) == _norm(title):
            s += 3
        elif _norm(title) in _norm(x.get("trackName", "")):
            s += 1
        if artist and _norm(artist) in _norm(x.get("artistName", "")):
            s += 3
        return s

    results.sort(key=score, reverse=True)
    if not results or score(results[0]) < 5:
        return None
    art = results[0].get("artworkUrl100")
    return art.replace("100x100bb.jpg", "1400x1400bb.jpg") if art else None


def read_tags(path):
    from mutagen.mp4 import MP4
    from mutagen.oggopus import OggOpus
    if path.endswith(".m4a"):
        a = MP4(path)
        g = lambda k: ((a.get(k) or [""])[0] or "")
        return g("\xa9nam"), g("\xa9ART"), g("\xa9alb")
    a = OggOpus(path)
    g = lambda k: ((a.get(k) or [""])[0] or "")
    return g("title"), g("artist"), g("album")


def upgrade_file(path, delay=3.0):
    """Returns True if the embedded cover was replaced with a larger one."""
    from .tags import tag  # reuse embed path via a minimal track object

    class _T:
        pass

    _, cur_size = current_cover(path)
    title, artist, album = read_tags(path)
    art = itunes_art(f"{artist} {album or title}", album, title, artist) \
        or itunes_art(f"{artist} {title}", album, title, artist)
    time.sleep(delay)
    if not art:
        return False
    try:
        raw = requests.get(art, headers=UA, timeout=30).content
        new = _jpeg(raw)
        from PIL import Image
        w = Image.open(io.BytesIO(new)).size[0]
        if w <= cur_size[0]:
            return False
    except Exception:
        return False
    t = _T()
    t.title, t.artists, t.album = title, artist, album
    t.album_artist, t.position, t.tracks_count, t.date = artist, 0, 0, ""
    # re-tag WITHOUT cover change would drop art; so embed directly:
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggopus import OggOpus
    from mutagen.flac import Picture
    import base64
    if path.endswith(".m4a"):
        a = MP4(path)
        a["covr"] = [MP4Cover(new, imageformat=MP4Cover.FORMAT_JPEG)]
        a.save()
    else:
        a = OggOpus(path)
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.data = new
        a["metadata_block_picture"] = [base64.b64encode(pic.write()).decode()]
        a.save()
    return True
