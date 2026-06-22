#!/usr/bin/env python3
"""
YouTube 视频下载引擎
使用 yt-dlp + ffmpeg 下载合并
"""

import os
import re
import shutil
import subprocess
import threading

import yt_dlp

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COOKIES_DIR = os.path.join(BASE_DIR, "youtube", "cookies")
os.makedirs(_COOKIES_DIR, exist_ok=True)
_COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")


def _find_ffmpeg():
    local = os.path.join(BASE_DIR, "ffmpeg.exe")
    if os.path.exists(local):
        return local
    _dir = os.path.dirname(os.path.abspath(__file__))
    local2 = os.path.join(_dir, "ffmpeg.exe")
    if os.path.exists(local2):
        return local2
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        if r.returncode == 0:
            return "ffmpeg"
    except: pass
    try:
        r = subprocess.run(["where", "ffmpeg"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().split("\n")[0]
    except: pass
    return None


def extract_video_id(url):
    """Extract YouTube video ID from URL"""
    m = re.search(r"(?:v=|youtu\.be/|/v/|/shorts/)([\w-]{11})", url)
    return m.group(1) if m else None


def detect_playlist(url):
    """Check if URL is a playlist"""
    return "list=" in url.lower()


def _find_cookies_file():
    """Find cookies.txt (prefer project root, then youtube/cookies/)"""
    if os.path.exists(_COOKIES_FILE):
        return _COOKIES_FILE
    candidates = [
        os.path.join(_COOKIES_DIR, "cookies.txt"),
        os.path.join(BASE_DIR, "youtube", "cookies.txt"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


# --- YouTube login (browser cookie extraction) ---

import http.cookiejar

_BROWSERS = [
    ("chrome", "Chrome"),
    ("edge", "Edge"),
    ("firefox", "Firefox"),
    ("brave", "Brave"),
    ("opera", "Opera"),
    ("chromium", "Chromium"),
    ("vivaldi", "Vivaldi"),
]

_ACTIVE_BROWSER = None


def list_browsers():
    return [{"key": key, "name": name} for key, name in _BROWSERS]


def _try_extract_cookies(browser_key):
    """Try to extract and validate YouTube cookies from a browser"""
    try:
        cookie_jar = yt_dlp.cookies.extract_cookies_from_browser(browser_key)
        has_session = False
        for c in cookie_jar:
            if hasattr(c, 'name') and c.name and c.value:
                name = c.name
                if name in ('__Secure-3PSID', '__Secure-3PAPISID', 'SAPISID', 'SSID',
                            'HSID', 'APISID', 'LOGIN_INFO', '__Secure-3PSIDCC'):
                    has_session = True
                    break
        return has_session
    except Exception:
        return False


def auto_extract_cookies():
    """Auto-scan all browsers for YouTube login state"""
    global _ACTIVE_BROWSER
    _ACTIVE_BROWSER = None

    for key, name in _BROWSERS:
        if _try_extract_cookies(key):
            _ACTIVE_BROWSER = key
            return {"ok": True, "message": f"Got login from {name}"}

    if os.path.exists(_COOKIES_FILE) and os.path.getsize(_COOKIES_FILE) > 100:
        with open(_COOKIES_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        if any(x in content for x in ('SAPISID', 'SSID', 'HSID', 'LOGIN_INFO')):
            _ACTIVE_BROWSER = None
            return {"ok": True, "message": "Got login from cookies.txt"}

    return {"ok": False, "message": "No valid YouTube login found in any browser.\nPlease login to YouTube in your browser first."}


def get_login_status():
    """Check current YouTube login status"""
    global _ACTIVE_BROWSER
    if _ACTIVE_BROWSER is not None:
        if _try_extract_cookies(_ACTIVE_BROWSER):
            return {"logged_in": True, "browser": _ACTIVE_BROWSER}
        _ACTIVE_BROWSER = None

    if os.path.exists(_COOKIES_FILE) and os.path.getsize(_COOKIES_FILE) > 100:
        with open(_COOKIES_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        if any(x in content for x in ('SAPISID', 'SSID', 'HSID', 'LOGIN_INFO')):
            return {"logged_in": True, "browser": None}
    return {"logged_in": False}


def logout():
    """Clear login state"""
    global _ACTIVE_BROWSER
    _ACTIVE_BROWSER = None
    if os.path.exists(_COOKIES_FILE):
        os.remove(_COOKIES_FILE)
    for f in os.listdir(_COOKIES_DIR):
        fp = os.path.join(_COOKIES_DIR, f)
        try:
            if os.path.isfile(fp): os.remove(fp)
        except: pass


def _build_ydl_opts(download=False, ffmpeg_path=None, quality="best", progress_hooks=None):
    """Build yt-dlp options with automatic cookie injection"""
    opts = {
        "quiet": not download,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 15,
        # 启用 Node.js 作为 JavaScript 运行时（用于解决 YouTube n challenge）
        "js_runtimes": {"node": {}},
    }

    if _ACTIVE_BROWSER is not None:
        opts["cookiesfrombrowser"] = (_ACTIVE_BROWSER,)
    else:
        cookies_file = _find_cookies_file()
        if cookies_file:
            opts["cookiefile"] = cookies_file

    if download:
        opts.update({
            "quiet": True,
            "progress_hooks": progress_hooks or [],
            "ffmpeg_location": ffmpeg_path,
            "format_sort": ["res:1080", "ext:mp4:m4a", "codec:h264:aac"],
            "format": "bv*+ba/b",
            "merge_output_format": "mp4",
            # 使用多个 player_client 以提高兼容性
            "extractor_args": {
                "youtube": {
                    "player_client": ["android_vr", "web", "ios", "mweb"],
                    "player_skip": ["webpage"]
                }
            }
        })
        if quality == "audio":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
            }]
    else:
        # info-only: 不限制格式，也不指定 player_client（避免某些视频格式不可用）
        opts.pop("format", None)
        opts.pop("extractor_args", None)
        opts.pop("format_sort", None)

    return opts


_INFO_TIMEOUT = 45


def _extract_info_with_timeout(url, ydl_opts, timeout=_INFO_TIMEOUT):
    """yt-dlp extract_info with timeout wrapper"""
    result = [None]
    error = [None]
    done = threading.Event()

    def worker():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result[0] = ydl.extract_info(url, download=False)
        except Exception as e:
            error[0] = e
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    if not done.wait(timeout=timeout):
        raise TimeoutError(f"Timeout getting YouTube video info (>{timeout}s)\nCheck network or try a proxy/VPN")
    if error[0]:
        raise error[0]
    return result[0]


def get_video_info(url):
    """Get YouTube video info via yt-dlp (with timeout)"""
    is_playlist = detect_playlist(url)

    ydl_opts = _build_ydl_opts(download=False)

    try:
        info = _extract_info_with_timeout(url, ydl_opts)
    except TimeoutError as e:
        raise RuntimeError(str(e))
    except Exception as e:
        msg = str(e)
        
        # 检查是否需要登录
        if "Sign in to confirm" in msg or "bot" in msg.lower():
            raise RuntimeError(
                "YouTube requires identity verification. Need browser cookies.\n"
                "Solution: Login to YouTube in your browser, then use the 'Auto Extract Cookies' button\n"
                "Or export cookies.txt using browser extension 'Get cookies.txt LOCALLY'"
            )
        
        # 检查是否格式不可用 - 尝试用最简配置重试
        if "format" in msg.lower() and ("not available" in msg.lower() or "unavailable" in msg.lower()):
            try:
                # 使用最简配置，不指定任何格式选项
                ydl_opts_fallback = {
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "socket_timeout": 15,
                    "extractor_args": {},  # 清空 extractor_args
                }
                
                if _ACTIVE_BROWSER is not None:
                    ydl_opts_fallback["cookiesfrombrowser"] = (_ACTIVE_BROWSER,)
                else:
                    cookies_file = _find_cookies_file()
                    if cookies_file:
                        ydl_opts_fallback["cookiefile"] = cookies_file
                
                info = _extract_info_with_timeout(url, ydl_opts_fallback)
            except Exception as e2:
                # 如果重试也失败，检查是否是登录问题
                msg2 = str(e2)
                if "Sign in to confirm" in msg2 or "bot" in msg2.lower():
                    raise RuntimeError(
                        "YouTube requires identity verification. Need browser cookies.\n"
                        "Solution: Login to YouTube in your browser, then use the 'Auto Extract Cookies' button\n"
                        "Or export cookies.txt using browser extension 'Get cookies.txt LOCALLY'"
                    )
                raise RuntimeError(f"Failed to get YouTube video info: {e}")
        else:
            raise RuntimeError(f"Failed to get YouTube video info: {e}")

    if info is None:
        raise RuntimeError("Unable to get video info")

    title = (info.get("title") or info.get("id") or "yt_video").strip()
    uploader = info.get("uploader") or info.get("channel") or info.get("creator") or ""
    duration = info.get("duration") or 0
    thumbnail = info.get("thumbnail") or ""

    formats = []
    seen_fmts = set()
    for f in (info.get("formats") or []):
        fmt_id = f.get("format_id", "")
        ext = f.get("ext", "")
        resolution = f.get("resolution") or f.get("format_note", "")
        filesize = f.get("filesize") or f.get("filesize_approx", 0)
        vcodec = f.get("vcodec", "none")
        if ext in ("mp4", "webm", "m4a") and vcodec != "none":
            key = (ext, resolution)
            if key not in seen_fmts:
                seen_fmts.add(key)
                formats.append({
                    "format_id": fmt_id,
                    "ext": ext,
                    "resolution": resolution,
                    "filesize": filesize,
                    "note": f.get("format_note", ""),
                })

    return {
        "title": title,
        "uploader": uploader or "YouTube",
        "duration": duration,
        "thumbnail": thumbnail,
        "video_id": extract_video_id(url) or info.get("id", ""),
        "formats": formats,
        "webpage_url": info.get("webpage_url") or url,
        "is_playlist": is_playlist,
    }


def download(url, output_dir, quality="best", on_progress=None, cancel_flag=None):
    """Download YouTube video using yt-dlp"""
    os.makedirs(output_dir, exist_ok=True)

    ffmpeg_path = _find_ffmpeg()
    if not ffmpeg_path:
        return False, "ffmpeg not found, put ffmpeg.exe in project directory"

    try:
        info = get_video_info(url)
        title = info["title"]
    except Exception as e:
        return False, f"Failed to get video info: {e}"

    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title).strip() or "yt_video"
    output_template = os.path.join(output_dir, f"{safe_title}.%(ext)s")

    def progress_hook(d):
        if cancel_flag and cancel_flag():
            raise Exception("Cancelled")
        if d.get("status") == "downloading":
            pct = 0.0
            if d.get("_percent_str"):
                try:
                    pct = float(d["_percent_str"].strip("% \n\r")) / 100.0
                except: pass
            if on_progress:
                on_progress(pct, f"Downloading... {d.get('_percent_str', '0%').strip()}")
        elif d.get("status") == "finished":
            if on_progress:
                on_progress(0.9, "Merging...")

    ydl_opts = _build_ydl_opts(download=True, ffmpeg_path=ffmpeg_path, quality=quality, progress_hooks=[progress_hook])
    ydl_opts["outtmpl"] = output_template

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if on_progress:
            on_progress(1.0, "Download complete")

        video_id = extract_video_id(url)
        for fname in os.listdir(output_dir):
            fpath = os.path.join(output_dir, fname)
            if not os.path.isfile(fpath):
                continue
            lower = fname.lower()
            if safe_title in fname or (video_id and video_id in fname):
                if lower.endswith((".mp4", ".webm", ".mkv", ".mp3")):
                    return True, fpath

        candidates = []
        for fname in os.listdir(output_dir):
            fpath = os.path.join(output_dir, fname)
            if os.path.isfile(fpath):
                lower = fname.lower()
                if lower.endswith((".mp4", ".webm", ".mkv", ".mp3")):
                    candidates.append((os.path.getmtime(fpath), fpath))
        if candidates:
            candidates.sort(reverse=True)
            return True, candidates[0][1]
        return False, "Download complete but output file not found"
    except Exception as e:
        return False, f"Download failed: {e}"
