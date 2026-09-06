"""CLI: resolve sources, download releases, tag, organize."""

import argparse
import os
import re
import sys
import time

from . import sources, tags
from .audio import Downloader


def detect(query):
    """Returns ('spotify-url', url) / ('deezer-url', url) / ('artist-name', q)."""
    if "open.spotify.com/" in query:
        return "spotify-url", query
    if "deezer.com/" in query:
        return "deezer-url", query
    return "artist-name", query


def build_downloader(args):
    cookie_file = args.cookie_file
    if args.cookies_from_browser and args.refresh_cookies:
        cookie_file = os.path.abspath(args.cookies or os.path.join(args.output, ".maxqual-cookies.txt"))
        probe = Downloader(cookie_file=None)
        try:
            probe.refresh_cookies_from_browser(args.cookies_from_browser, cookie_file)
        except RuntimeError as e:
            print(f"warning: {e}; continuing without an exported jar")
            cookie_file = None
    dl = Downloader(cookie_file=cookie_file,
                    cookies_from_browser=None if cookie_file else args.cookies_from_browser,
                    deno_dir=args.deno_dir, tmp_dir=os.path.join(args.output, ".maxqual-tmp"))
    return dl


def process_release(dl, rel, root, cover_cache, sleep=0.4, artist_mode=False):
    """Download one release into root/<name>/. Returns (ok, fail)."""
    outdir = os.path.join(root, tags.sanitize(rel.title))
    os.makedirs(outdir, exist_ok=True)
    cover_url = rel.cover_url
    ok = fail = 0
    lines = []
    for attempt in (1, 2):  # second pass retries misses
        for t in rel.tracks:
            base = tags.sanitize(f"{int(t.position or 0):02d} - {t.artists} - {t.title}") \
                if t.position else tags.sanitize(f"{t.artists} - {t.title}")
            final = None
            for ext in ("m4a", "opus"):
                if os.path.exists(os.path.join(outdir, f"{base}.{ext}")):
                    final = ext
                    break
            if final:
                if f"{base}.{final}" not in lines:
                    lines.append(f"{base}.{final}")
                continue
            vid = dl.search(t.artists, t.title, t.duration)
            if not vid:
                if attempt == 2:
                    print(f"    MISS: {base}")
                fail += 1 if attempt == 2 else 0
                continue
            path, ext = dl.download(vid)
            if not path:
                if attempt == 2:
                    print(f"    FAIL: {base}")
                fail += 1 if attempt == 2 else 0
                continue
            dest = os.path.join(outdir, f"{base}.{ext}")
            os.replace(path, dest)
            cover = None
            cu = t.cover_url or cover_url
            if cu:
                cf = tags.fetch_cover(cu, cover_cache)
                if cf:
                    cover = open(cf, "rb").read()
            try:
                tags.tag(dest, ext, t, cover)
            except Exception as e:
                print(f"    TAG-ERR {base}: {e}")
            if f"{base}.{ext}" not in lines:
                lines.append(f"{base}.{ext}")
            ok += 1
            print(f"    ok [{ext}] {base}")
            time.sleep(sleep)
    tags.write_m3u(outdir, rel.title, lines)
    if cover_url:
        cf = tags.fetch_cover(cover_url, cover_cache)
        if cf:
            tags.write_folder_jpg(outdir, open(cf, "rb").read())
    return ok, fail


def cmd_download(args):
    kind, q = detect(args.query)
    releases = []
    artist_root = None
    if kind == "artist-name":
        art = sources.deezer_search_artist(q)
        if not art:
            sys.exit(f"no deezer artist found for {q!r}")
        print(f"artist: {art['name']} ({art['nb_album']} releases)")
        artist_root = tags.sanitize(art["name"])
        rels = sources.deezer_artist_releases(art["id"])
        print(f"{len(rels)} releases (album/single/ep)")
        todo = rels
    elif kind == "deezer-url":
        r = sources.deezer_release_by_url(q)
        if r is None:
            sys.exit("unsupported deezer url (use /album or /playlist)")
        todo = r
    else:
        r = sources.spotify_release_by_url(q)
        if r is None:
            sys.exit("unsupported spotify url (use /playlist or /album)")
        todo = r

    dl = build_downloader(args)
    root = os.path.join(args.output, tags.sanitize(artist_root)) if artist_root else args.output
    os.makedirs(root, exist_ok=True)
    cover_cache = os.path.join(root, ".maxqual-covers")

    total_ok = total_fail = 0
    for rel in todo:
        have = 0
        outdir = os.path.join(root, tags.sanitize(rel.title))
        if os.path.isdir(outdir):
            have = len([f for f in os.listdir(outdir) if f.endswith((".m4a", ".opus"))])
        if have and have >= len(rel.tracks):
            print(f"  [cached] {rel.title}")
            continue
        print(f"  {rel.title} ({len(rel.tracks)} tracks)")
        ok, fail = process_release(dl, rel, root, cover_cache)
        total_ok += ok
        total_fail += fail
    print(f"done: {total_ok} downloaded, {total_fail} failed")


def cmd_covers(args):
    from .covers import upgrade_file
    n = up = 0
    for root, dirs, files in os.walk(args.directory):
        for fn in sorted(files):
            if not fn.endswith((".m4a", ".opus")):
                continue
            n += 1
            if upgrade_file(os.path.join(root, fn), delay=args.delay):
                up += 1
                print(f"  UP {fn[:70]}")
    print(f"checked {n}, upgraded {up}")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="maxqual",
        description="Build a music library at the highest quality the source serves, "
                    "with complete tags, covers and playlists.")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="download a release, playlist, or artist discography")
    d.add_argument("query", help="Spotify playlist/album URL, Deezer album/playlist/artist URL, "
                                 "or an artist name")
    d.add_argument("-o", "--output", default=".", help="output root (default: cwd)")
    d.add_argument("--cookie-file", help="Netscape cookies file for the audio source")
    d.add_argument("--cookies-from-browser", help="browser to read a session from "
                                                  "(firefox, chrome, brave, ...)")
    d.add_argument("--refresh-cookies", action="store_true",
                   help="export a fresh cookie jar from the browser first (recommended; "
                        "session tokens rotate)")
    d.add_argument("--cookies", help="where to write the exported jar "
                                     "(default: <output>/.maxqual-cookies.txt)")
    d.add_argument("--deno-dir", help="directory containing a deno binary "
                                      "(needed for YouTube JS challenges)")
    d.set_defaults(func=cmd_download)

    c = sub.add_parser("covers", help="upgrade embedded cover art where larger art exists")
    c.add_argument("directory")
    c.add_argument("--delay", type=float, default=3.0, help="seconds between lookups")
    c.set_defaults(func=cmd_covers)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
