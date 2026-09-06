"""Tagging (mutagen) and cover art handling."""

import base64
import io
import os
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (maxqual)"}


def sanitize(s):
    return re.sub(r'[<>:"/\\|?*]', "-", s or "").strip()


def fetch_cover(url, cache_dir, cache={}):
    if not url:
        return None
    if url in cache:
        return cache[url]
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, str(abs(hash(url))) + ".jpg")
    if not os.path.exists(path):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            open(path, "wb").write(r.content)
        except requests.RequestException:
            return None
    cache[url] = path
    return path


def _jpeg(data):
    """Normalize any image to JPEG bytes (for m4a covr / opus pictures)."""
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    out = io.BytesIO()
    im.save(out, "JPEG", quality=92)
    return out.getvalue()


def tag(path, ext, track, cover_data=None):
    """track: object with title, artists, album, album_artist, position,
    tracks_count, date (all strings/ints). cover_data: raw image bytes."""
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggopus import OggOpus
    from mutagen.flac import Picture

    if cover_data:
        try:
            cover_data = _jpeg(cover_data)
        except Exception:
            cover_data = None

    if ext == "m4a":
        a = MP4(path)
        a["\xa9nam"] = [track.title]
        a["\xa9ART"] = [track.artists]
        a["\xa9alb"] = [track.album or ""]
        a["aART"] = [track.album_artist or track.artists]
        if track.position:
            a["trkn"] = [(int(track.position), int(track.tracks_count or 0))]
        if track.date:
            a["\xa9day"] = [str(track.date)]
        if cover_data:
            a["covr"] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
        a.save()
    else:
        a = OggOpus(path)
        a["title"] = track.title
        a["artist"] = track.artists
        a["album"] = track.album or ""
        a["albumartist"] = track.album_artist or track.artists
        if track.position:
            a["tracknumber"] = f"{int(track.position)}/{int(track.tracks_count or 0)}"
        if track.date:
            a["date"] = str(track.date)
        if cover_data:
            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.data = cover_data
            a["metadata_block_picture"] = [base64.b64encode(pic.write()).decode()]
        a.save()


def write_folder_jpg(directory, cover_data):
    if cover_data:
        try:
            open(os.path.join(directory, "folder.jpg"), "wb").write(_jpeg(cover_data))
        except Exception:
            pass


def write_m3u(directory, name, filenames):
    with open(os.path.join(directory, sanitize(name) + ".m3u8"), "w") as f:
        f.write("\n".join(filenames) + "\n")
