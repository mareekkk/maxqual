"""Metadata sources: Deezer (open, no auth) and Spotify (client credentials).

Deezer covers artist/album/playlist without any key. Spotify is needed for
playlists; anonymous client-credential pairs are quota-capped globally, so
retries with backoff are built in and credentials can be overridden via
MAXQUAL_SPOTIFY_ID / MAXQUAL_SPOTIFY_SECRET.
"""

import os
import re
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (maxqual)"}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _get(url, params=None, retries=4, backoff=2.0):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(backoff * (i + 1))
                continue
        except requests.RequestException:
            time.sleep(backoff * (i + 1))
    return {}


class Track:
    __slots__ = ("title", "artists", "album", "album_artist", "position",
                 "tracks_count", "date", "duration", "cover_url")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s) or ("" if s != "tracks_count" else 0))


class Release:
    __slots__ = ("title", "artist", "date", "cover_url", "tracks")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))


# ---------------------------------------------------------------- Deezer

def deezer(path):
    return _get("https://api.deezer.com" + path)


def deezer_track(tid, main_artist):
    info = deezer(f"/track/{tid}")
    feats = [c["name"] for c in (info.get("contributors") or [])
             if c.get("name") and _norm(c["name"]) != _norm(main_artist)]
    seen, artists = {_norm(main_artist)}, main_artist
    for f in feats:
        if _norm(f) not in seen:
            artists += ", " + f
            seen.add(_norm(f))
    return Track(
        title=info.get("title", ""), artists=artists,
        album=(info.get("album") or {}).get("title", ""),
        album_artist=main_artist,
        position=info.get("track_position") or 0,
        date=(info.get("release_date") or "")[:10],
        duration=info.get("duration") or 0,
        cover_url=(info.get("album") or {}).get("cover_xl"),
    )


def deezer_release(album_id):
    a = deezer(f"/album/{album_id}")
    rel = Release(
        title=a.get("title", ""), artist=(a.get("artist") or {}).get("name", ""),
        date=(a.get("release_date") or "")[:10],
        cover_url=a.get("cover_xl"), tracks=[],
    )
    for t in (a.get("tracks") or {}).get("data") or []:
        rel.tracks.append(deezer_track(t["id"], rel.artist))
        time.sleep(0.1)
    return rel


def deezer_artist_releases(artist_id, types=("album", "single", "ep")):
    rels = deezer(f"/artist/{artist_id}/albums?limit=500").get("data") or []
    return [r for r in rels if r.get("record_type") in types]


def deezer_search_artist(name):
    data = _get("https://api.deezer.com/search/artist",
                params={"q": name, "limit": 5}).get("data") or []
    if not data:
        return None
    # prefer the entry whose name matches the query with the most fans
    exact = [d for d in data if _norm(d["name"]) == _norm(name)]
    pool = exact or data
    return max(pool, key=lambda d: d.get("nb_fan") or 0)


def deezer_release_by_url(url):
    m = re.search(r"deezer\.com/(?:[a-z]{2}/)?(album|playlist)/(\d+)", url)
    if not m:
        return None
    kind, rid = m.groups()
    if kind == "album":
        return [deezer_release(rid)]
    pl = deezer(f"/playlist/{rid}")
    # playlists: group tracks by album so each becomes its own release
    groups = {}
    for t in (pl.get("tracks") or {}).get("data") or []:
        groups.setdefault((t.get("album") or {}).get("title") or "Playlist", []).append(t)
    rels = []
    for album_title, tracks in groups.items():
        rel = Release(title=pl.get("title", album_title), artist=pl.get("creator", {}).get("name", ""),
                      date="", cover_url=pl.get("picture_xl"), tracks=[])
        for i, t in enumerate(tracks, 1):
            rel.tracks.append(Track(
                title=t["title"], artists=", ".join({a["name"] for a in t.get("artists", [])}) or t["artist"]["name"],
                album=album_title, album_artist=rel.artist, position=i,
                tracks_count=len(tracks), date="",
                duration=t.get("duration") or 0,
                cover_url=(t.get("album") or {}).get("cover_xl"),
            ))
        rels.append(rel)
    return rels


# --------------------------------------------------------------- Spotify

def _spotify_token():
    cid = os.environ.get("MAXQUAL_SPOTIFY_ID", "5f573c9620494bae87890c0f08a60293")
    csc = os.environ.get("MAXQUAL_SPOTIFY_SECRET", "212476d9b0f3472eaa762d90b19b0ba8")
    for i in range(5):
        try:
            r = requests.post("https://accounts.spotify.com/api/token",
                              data={"grant_type": "client_credentials",
                                    "client_id": cid, "client_secret": csc},
                              headers=UA, timeout=30)
            if r.status_code == 200:
                return r.json()["access_token"]
        except requests.RequestException:
            pass
        time.sleep(5 * (i + 1))
    return None


def spotify_release_by_url(url):
    """Playlist or album URL -> list of Release (one per distinct album group)."""
    m = re.search(r"open\.spotify\.com/(playlist|album)/([A-Za-z0-9]+)", url)
    if not m:
        return None
    kind, rid = m.groups()
    token = _spotify_token()
    if not token:
        raise RuntimeError("could not obtain Spotify token (quota? set "
                           "MAXQUAL_SPOTIFY_ID/SECRET to your own app credentials)")
    hdr = {"Authorization": f"Bearer {token}"}
    if kind == "album":
        a = _get(f"https://api.spotify.com/v1/albums/{rid}", retries=1)
        if not a.get("name"):
            return None
        rel = Release(title=a["name"], artist=(a.get("artists") or [{}])[0].get("name", ""),
                      date=a.get("release_date", ""), cover_url=next(
                          iter(sorted((i["url"] for i in a.get("images", [])), reverse=True)), ""),
                      tracks=[])
        for i, t in enumerate(a.get("tracks", {}).get("items") or [], 1):
            arts = ", ".join(x["name"] for x in t.get("artists") or [])
            rel.tracks.append(Track(
                title=t["name"], artists=arts, album=a["name"],
                album_artist=rel.artist, position=t.get("track_number") or i,
                tracks_count=a.get("total_tracks") or len(rel.tracks) + 1,
                date=a.get("release_date", ""), duration_ms=t.get("duration_ms", 0) // 1000,
                cover_url=rel.cover_url,
            ))
        return [rel]
    # playlist: preserve playlist order, group folder by playlist name
    pl = _get(f"https://api.spotify.com/v1/playlists/{rid}", retries=1)
    if not pl.get("name"):
        return None
    items = (pl.get("tracks") or {}).get("items") or []
    cover = next(iter(sorted((i["url"] for i in pl.get("images", [])), reverse=True)), "")
    rel = Release(title=pl["name"], artist="", date="", cover_url=cover, tracks=[])
    for i, item in enumerate(items, 1):
        t = item.get("track") or {}
        if not t.get("name"):
            continue
        arts = ", ".join(x["name"] for x in t.get("artists") or [])
        album = (t.get("album") or {})
        rel.tracks.append(Track(
            title=t["name"], artists=arts, album=album.get("name", ""),
            album_artist=arts.split(",")[0] if arts else "",
            position=i, tracks_count=len(items),
            date=album.get("release_date", ""),
            duration=(t.get("duration_ms") or 0) // 1000,
            cover_url=next(iter(sorted((im["url"] for im in album.get("images", [])), reverse=True)), ""),
        ))
    return [rel]
