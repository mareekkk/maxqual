# maxqual

Build a music library at the **highest quality the source serves**, with complete
tags, cover art and per-release organization.

maxqual is a standalone CLI for people who curate permanent local libraries
(e.g. for Jellyfin/Plex/navidrome). It resolves release metadata, matches
tracks, downloads audio **natively (no re-encode)**, tags it properly, and
organizes it into per-release folders with playlists and artwork.

## What makes it different

- **Zero-transcode pipeline.** Streams are kept in their native container.
  Audio is never re-encoded, so what you keep is exactly what the source
  served — no generational loss.
- **Quality-tier preference.** When a higher audio tier is available to the
  session you supply, it is preferred automatically; otherwise the best
  publicly available stream is used.
- **Discography-aware.** Point it at an artist and it fetches albums, EPs and
  singles as separate, properly numbered releases with an `.m3u8` each.
- **Open metadata first.** Release/track metadata comes from Deezer's public
  API (no key, no quota dance) for artist and album URLs; Spotify
  playlists/albums are supported with client credentials (your own app key,
  or a shared fallback with retries).
- **Cover art maintenance.** `maxqual covers` re-embeds artwork when a
  strictly larger image can be found, and writes `folder.jpg` per release.

## How it works

```
metadata source (Deezer / Spotify)
        │  release, tracklist, durations, artwork URL
        ▼
track matching (yt-dlp search, duration-scored)
        │
        ▼
audio download (yt-dlp; native formats only)
        │  m4a / opus, no conversion
        ▼
tagging + organization (mutagen)
   NN - Artists - Title.ext   +   Release.m3u8   +   folder.jpg
```

## Install

Requires Python 3.10+, `ffmpeg` on PATH, and (recommended) a
[deno](https://deno.land) binary — YouTube's JS challenges need a JS runtime
that `yt-dlp` can find.

```bash
pipx install maxqual        # or: pip install maxqual
```

From source:

```bash
git clone https://github.com/mareekkk/maxqual
pipx install ./maxqual
```

## Usage

```bash
# an artist's discography (Deezer metadata; albums + EPs + singles)
maxqual download "Jeff Kaale" -o ~/Music

# a specific album or playlist
maxqual download "https://www.deezer.com/album/123456" -o ~/Music
maxqual download "https://open.spotify.com/playlist/..." -o ~/Music

# use a logged-in browser session (recommended; tokens rotate, so export fresh)
maxqual download "https://open.spotify.com/playlist/..." \
    --cookies-from-browser firefox --refresh-cookies -o ~/Music

# upgrade embedded cover art across a library
maxqual covers ~/Music
```

Resumable by design: existing files are skipped, so re-running a command
retries only what is missing.

### Optional: PO token provider

Some streams require a proof-of-origin token. If you run the community
[bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)
server locally (loopback only), `yt-dlp` picks it up automatically and maxqual
benefits with no extra configuration:

```bash
docker run -d --init --restart unless-stopped \
    -p 127.0.0.1:4416:4416 brainicism/bgutil-ytdlp-pot-provider
```

### Session cookies

Session cookies are credentials. maxqual exports them to a mode-600 file when
you pass `--refresh-cookies`, never prints them, and you should delete the
file when you are done. Anonymous operation also works and simply resolves to
the best public stream.

## Project layout

```
src/maxqual/
  audio.py    # yt-dlp wrapper: search, native download, cookie export
  sources.py  # Deezer + Spotify metadata
  tags.py     # mutagen tagging, covers, m3u, folder.jpg
  covers.py   # cover-art upgrade pass
  cli.py      # command line interface
```

## Legal

maxqual is a tool. It does not host, index or redistribute any content, and it
ships without credentials of any kind.

- You are responsible for what you download and for complying with the terms
  of the platforms you interact with and the copyright of the material
  involved.
- Intended uses include: content you own or created, content published under
  permissive licenses (e.g. Creative Commons, public domain), and anything
  you are licensed to archive.
- The authors do not condone infringement and provide no support for it.

Extraction technology is a moving target; if a source changes its player
response format, this tool inherits whatever `yt-dlp` handles.

## License

MIT — see [LICENSE](LICENSE).
