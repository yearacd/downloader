#!/usr/bin/env python3
"""
Twitter/X 视频下载引擎
使用 yt-dlp + ffmpeg 下载合并
支持浏览器 Cookie 登录以获取 guest token
"""

import os
import re
import subprocess
import json

import yt_dlp

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COOKIES_DIR = os.path.join(BASE_DIR, "twitter", "cookies")
_COOKIES_FILE = os.path.join(BASE_DIR, "twitter_cookies.txt")
_ACTIVE_BROWSER = None

# 支持的浏览器列表
_BROWSERS = [
    ("chrome", "Chrome"),
    ("firefox", "Firefox"),
    ("edge", "Edge"),
    ("safari", "Safari"),
    ("opera", "Opera"),
    ("brave", "Brave"),
    ("vivaldi", "Vivaldi"),
]

os.makedirs(_COOKIES_DIR, exist_ok=True)


def _try_extract_cookies(browser_key):
    """尝试从指定浏览器提取 Twitter cookies"""
    try:
        # 使用 browser_cookie3 库提取 cookies
        try:
            import browser_cookie3 as bc
            
            browsers = {
                "chrome": bc.Chrome,
                "firefox": bc.Firefox,
                "edge": bc.Edge,
                "safari": bc.Safari,
                "opera": bc.Opera,
                "brave": bc.Brave,
                "vivaldi": bc.Vivaldi,
            }
            
            browser_class = browsers.get(browser_key)
            if not browser_class:
                return False
            
            # 获取所有 cookies
            cj = browser_class()
            all_cookies = cj.load()
            
            # 过滤出 Twitter/X 相关的 cookies
            twitter_cookies = []
            for cookie in all_cookies:
                if 'twitter.com' in cookie.domain or 'x.com' in cookie.domain:
                    twitter_cookies.append(cookie)
            
            if not twitter_cookies:
                return False
            
            # 检查是否有必要的 Twitter cookies
            cookie_names = [c.name for c in twitter_cookies]
            has_auth = any(name in cookie_names for name in ['auth_token', 'ct0', 'twid'])
            
            if not has_auth:
                return False
            
            # 保存 cookies 到文件
            cookies_file = os.path.join(_COOKIES_DIR, f"{browser_key}.txt")
            with open(cookies_file, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for cookie in twitter_cookies:
                    f.write(f"{cookie.domain}\tTRUE\t{cookie.path}\t{cookie.secure and 'TRUE' or 'FALSE'}\t{cookie.expires or 0}\t{cookie.name}\t{cookie.value}\n")
            
            # 同时保存到主 cookies 文件
            with open(_COOKIES_FILE, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for cookie in twitter_cookies:
                    f.write(f"{cookie.domain}\tTRUE\t{cookie.path}\t{cookie.secure and 'TRUE' or 'FALSE'}\t{cookie.expires or 0}\t{cookie.name}\t{cookie.value}\n")
            
            return True
            
        except ImportError:
            # 如果没有 browser_cookie3，尝试使用 yt-dlp 内置功能
            return False
            
    except Exception as e:
        print(f"Error extracting cookies from {browser_key}: {e}")
        return False


def auto_extract_cookies():
    """自动扫描所有浏览器提取 Twitter cookies"""
    global _ACTIVE_BROWSER
    _ACTIVE_BROWSER = None
    
    for key, name in _BROWSERS:
        if _try_extract_cookies(key):
            _ACTIVE_BROWSER = key
            return {"ok": True, "message": f"已从 {name} 获取 Twitter 登录信息"}
    
    # 检查是否有现有的 cookies 文件
    if os.path.exists(_COOKIES_FILE) and os.path.getsize(_COOKIES_FILE) > 100:
        with open(_COOKIES_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        if any(x in content for x in ('auth_token', 'ct0', 'twid')):
            _ACTIVE_BROWSER = None
            return {"ok": True, "message": "已从 cookies.txt 获取登录信息"}
    
    return {
        "ok": False,
        "message": "未在任何浏览器中找到有效的 Twitter 登录信息。\n请先在浏览器中登录 Twitter/X。"
    }


def get_login_status():
    """检查当前 Twitter 登录状态"""
    global _ACTIVE_BROWSER
    
    if _ACTIVE_BROWSER is not None:
        if _try_extract_cookies(_ACTIVE_BROWSER):
            return {"logged_in": True, "browser": _ACTIVE_BROWSER}
        _ACTIVE_BROWSER = None
    
    if os.path.exists(_COOKIES_FILE) and os.path.getsize(_COOKIES_FILE) > 100:
        with open(_COOKIES_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        if any(x in content for x in ('auth_token', 'ct0', 'twid')):
            return {"logged_in": True, "browser": None}
    
    return {"logged_in": False}


def logout():
    """清除登录状态"""
    global _ACTIVE_BROWSER
    _ACTIVE_BROWSER = None
    if os.path.exists(_COOKIES_FILE):
        os.remove(_COOKIES_FILE)
    for f in os.listdir(_COOKIES_DIR):
        fp = os.path.join(_COOKIES_DIR, f)
        try:
            if os.path.isfile(fp):
                os.remove(fp)
        except:
            pass


def list_browsers():
    """列出支持提取 cookie 的浏览器"""
    available = []
    for key, name in _BROWSERS:
        try:
            import browser_cookie3 as bc
            browsers = {
                "chrome": bc.Chrome,
                "firefox": bc.Firefox,
                "edge": bc.Edge,
                "safari": bc.Safari,
                "opera": bc.Opera,
                "brave": bc.Brave,
                "vivaldi": bc.Vivaldi,
            }
            browser_class = browsers.get(key)
            if browser_class:
                cj = browser_class().get_cookies_for_domain("x.com")
                if cj:
                    available.append({"key": key, "name": name, "has_cookies": True})
                else:
                    available.append({"key": key, "name": name, "has_cookies": False})
        except:
            available.append({"key": key, "name": name, "has_cookies": False})
    return available


def open_twitter_login():
    """在默认浏览器中打开 Twitter 登录页面"""
    import webbrowser
    webbrowser.open("https://x.com/i/flow/login")


def _find_ffmpeg():
    """查找 ffmpeg"""
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


def _find_cookies_file():
    """查找 Twitter cookies 文件"""
    if os.path.exists(_COOKIES_FILE) and os.path.getsize(_COOKIES_FILE) > 100:
        return _COOKIES_FILE
    
    # 检查浏览器特定的 cookies 文件
    if _ACTIVE_BROWSER:
        browser_cookie = os.path.join(_COOKIES_DIR, f"{_ACTIVE_BROWSER}.txt")
        if os.path.exists(browser_cookie) and os.path.getsize(browser_cookie) > 100:
            return browser_cookie
    
    return None


def extract_tweet_id(url):
    """从 URL 中提取 tweet ID"""
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else None


def get_video_info(url):
    """用 yt-dlp 获取 X 视频信息，返回 dict"""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "noplaylist": True,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    }
    
    # 添加 cookies 支持
    if _ACTIVE_BROWSER is not None:
        ydl_opts["cookiesfrombrowser"] = (_ACTIVE_BROWSER,)
    else:
        cookies_file = _find_cookies_file()
        if cookies_file:
            ydl_opts["cookiefile"] = cookies_file

    text_output = []
    def hook(d):
        text_output.append(ydl_opts)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as e:
            error_msg = str(e)
            
            # 检查是否是 guest token 错误
            if "guest token" in error_msg.lower() or "bad guest" in error_msg.lower():
                raise RuntimeError(
                    "Twitter/X guest token 失效。\n"
                    "解决方案：\n"
                    "1. 请点击右上角的 'Twitter未登录' 按钮进行登录\n"
                    "2. 确保已在浏览器中登录 Twitter/X\n"
                    "3. 如果持续失败，可能需要更新 yt-dlp: pip install -U yt-dlp"
                )
            
            raise RuntimeError(f"获取 X 视频信息失败: {e}")

    if info is None:
        raise RuntimeError("无法获取视频信息")

    # yt-dlp 返回的格式
    title = (info.get("title") or info.get("id") or "x_video").strip()
    # 清理不安全字符
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title).strip() or "x_video"

    # 获取上传者
    uploader = info.get("uploader") or info.get("channel") or info.get("creator") or ""

    # 获取时长
    duration = info.get("duration") or 0

    # 获取缩略图
    thumbnail = info.get("thumbnail") or ""

    # 获取可用格式列表（简要信息）
    formats = []
    for f in (info.get("formats") or []):
        fmt_id = f.get("format_id", "")
        ext = f.get("ext", "")
        resolution = f.get("resolution", "") or f.get("format_note", "")
        filesize = f.get("filesize") or f.get("filesize_approx", 0)
        if ext in ("mp4", "m4a", "webm") and f.get("vcodec") != "none":
            formats.append({
                "format_id": fmt_id,
                "ext": ext,
                "resolution": resolution,
                "filesize": filesize,
                "note": f.get("format_note", ""),
            })

    return {
        "title": title,
        "uploader": uploader or "Twitter User",
        "duration": duration,
        "thumbnail": thumbnail,
        "tweet_id": extract_tweet_id(url) or info.get("id", ""),
        "formats": formats,
        "webpage_url": info.get("webpage_url") or url,
    }


def download(url, output_dir, quality="best", on_progress=None, cancel_flag=None):
    """使用 yt-dlp 下载 X 视频"""
    os.makedirs(output_dir, exist_ok=True)

    # 检查 ffmpeg (yt-dlp 合并需要)
    ffmpeg_path = _find_ffmpeg()
    if not ffmpeg_path:
        return False, "未找到 ffmpeg，请将 ffmpeg.exe 放在项目目录"

    # 获取标题用于文件名
    try:
        info = get_video_info(url)
        title = info["title"]
    except Exception as e:
        return False, f"获取视频信息失败: {e}"

    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title).strip() or "x_video"
    output_template = os.path.join(output_dir, f"{safe_title}.%(ext)s")

    def progress_hook(d):
        if d.get("status") == "downloading":
            pct = 0.0
            if d.get("_percent_str"):
                try:
                    pct = float(d["_percent_str"].strip("% \n\r")) / 100.0
                except: pass
            if on_progress:
                on_progress(pct, f"下载中... {d.get('_percent_str', '0%').strip()}")
        elif d.get("status") == "finished":
            if on_progress:
                on_progress(0.9, "合并处理中...")

    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "progress_hooks": [progress_hook],
        "merge_output_format": "mp4",
        "ffmpeg_location": ffmpeg_path,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    }
    
    # 添加 cookies 支持
    if _ACTIVE_BROWSER is not None:
        ydl_opts["cookiesfrombrowser"] = (_ACTIVE_BROWSER,)
    else:
        cookies_file = _find_cookies_file()
        if cookies_file:
            ydl_opts["cookiefile"] = cookies_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if on_progress:
            on_progress(1.0, "下载完成")

        # 找到下载的文件
        tweet_id = extract_tweet_id(url)
        for fname in os.listdir(output_dir):
            fpath = os.path.join(output_dir, fname)
            lower = fname.lower()
            # 匹配文件名（youtube-dl 输出）
            if safe_title in fname or (tweet_id and tweet_id in fname):
                if lower.endswith(".mp4") or lower.endswith(".webm") or lower.endswith(".mkv"):
                    return True, fpath

        # 兜底：找最近修改的 mp4
        mp4s = [os.path.join(output_dir, f) for f in os.listdir(output_dir)
                if f.lower().endswith(".mp4")]
        if mp4s:
            newest = max(mp4s, key=os.path.getctime)
            return True, newest

        return False, "下载完成但未找到输出文件"

    except Exception as e:
        return False, f"下载失败: {e}"
