"""Audio acquisition: native YouTube streams, itag 141 (Premium AAC 256k) first.

The core trick this package exists for:
- YouTube's best anonymous audio is itag 251 (Opus ~136k) / 140 (AAC 129k).
- itag 141 (AAC ~258k) is served only to YouTube Music Premium sessions, only
  via the music.youtube.com player, and only when a valid GVS PO token is
  presented. yt-dlp >= 2025 handles the last part automatically if the
  bgutil-ytdlp-pot-provider plugin has a reachable token provider.
- Streams are kept NATIVE (no transcode). webm/opus is remuxed losslessly
  into an Ogg Opus container so tags can be embedded.
"""

import glob
import os
import subprocess

MUSIC_URL = "https://music.youtube.com/watch?v={id}"
WATCH_URL = "https://www.youtube.com/watch?v={id}"


class Downloader:
    def __init__(self, cookie_file=None, cookies_from_browser=None, ytdlp="yt-dlp",
                 deno_dir=None, tmp_dir=".maxqual-tmp"):
        import shutil
        self.ytdlp = ytdlp
        self.tmp = tmp_dir
        os.makedirs(self.tmp, exist_ok=True)
        self.env = dict(os.environ)
        if not deno_dir:
            # auto-detect a JS runtime for YouTube's signature challenges
            if shutil.which("deno", path=self.env.get("PATH", "")):
                deno_dir = None  # already reachable
            else:
                home = os.path.expanduser("~")
                for cand in (os.path.join(home, ".deno/bin"),       # deno default
                             os.path.join(home, ".config/spotdl")): # spotdl's copy
                    if os.path.exists(os.path.join(cand, "deno")):
                        deno_dir = cand
                        break
        if deno_dir:
            self.env["PATH"] = deno_dir + os.pathsep + self.env.get("PATH", "")
        self.cookie_args = []
        if cookies_from_browser:
            self.cookie_args = ["--cookies-from-browser", cookies_from_browser]
        elif cookie_file:
            self.cookie_args = ["--cookies", cookie_file]

    def run(self, cmd, timeout=300):
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, env=self.env)

    def json(self, url, timeout=120):
        r = self.run([self.ytdlp, "-J", "--flat-playlist", "--no-warnings"] +
                     self.cookie_args + [url], timeout=timeout)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        try:
            import json
            return json.loads(r.stdout)
        except ValueError:
            return None

    def search(self, artists, title, duration=None, limit=6):
        """ytsearch with duration scoring. Returns video id or None."""
        data = self.json(f"ytsearch{limit}:{artists} - {title}")
        entries = (data or {}).get("entries") or []
        best, best_key = None, None
        for e in entries:
            if not e or not e.get("id") or e.get("duration") is None:
                continue
            diff = abs(e["duration"] - (duration or e["duration"]))
            key = (diff, -(e.get("view_count") or 0))
            if best_key is None or key < best_key:
                best, best_key = e, key
        return best["id"] if best else None

    def download(self, video_id):
        """Best available audio, native. Returns (path, ext) or (None, None)."""
        for stale in glob.glob(os.path.join(self.tmp, "dl.*")):
            os.remove(stale)
        for url, fmts in ((MUSIC_URL.format(id=video_id), "141/251/140"),
                          (WATCH_URL.format(id=video_id), "251/140")):
            self.run([self.ytdlp, "-f", fmts, "--no-warnings"] +
                     self.cookie_args +
                     ["-o", os.path.join(self.tmp, "dl.%(ext)s"), url])
            for ext in ("m4a", "webm", "opus", "mp4"):
                p = os.path.join(self.tmp, f"dl.{ext}")
                if os.path.exists(p):
                    if ext == "webm":
                        out = os.path.join(self.tmp, "dl.opus")
                        r = self.run(["ffmpeg", "-y", "-loglevel", "error",
                                      "-i", p, "-c", "copy", out], timeout=120)
                        if r.returncode == 0 and os.path.exists(out):
                            os.remove(p)
                            return out, "opus"
                    return p, ext
        return None, None

    def refresh_cookies_from_browser(self, browser, out_file):
        """Export a live browser jar to a Netscape file via yt-dlp itself.

        SIDTS session tokens rotate quickly; do this once per run. The file
        contains live credentials: keep it mode 600 and delete when done.
        """
        if os.path.exists(out_file):
            os.remove(out_file)
        self.run([self.ytdlp, "--cookies-from-browser", browser,
                  "--cookies", out_file, "--simulate",
                  "https://www.youtube.com/robots.txt"], timeout=120)
        if not os.path.exists(out_file) or os.path.getsize(out_file) < 500:
            raise RuntimeError(f"cookie export from {browser} failed "
                               "(browser running with locked profile? not logged in?)")
        os.chmod(out_file, 0o600)
        return out_file
