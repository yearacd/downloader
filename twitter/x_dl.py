#!/usr/bin/env python3
"""
Twitter/X 视频下载引擎
使用 yt-dlp + ffmpeg 下载合并
"""

import os
import re
import subprocess

import yt_dlp

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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

    text_output = []
    def hook(d):
        text_output.append(ydl_opts)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as e:
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
