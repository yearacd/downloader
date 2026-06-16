#!/usr/bin/env python3
"""
Bilibili 视频下载引擎
使用 Bilibili API 获取视频流 + ffmpeg 下载合并
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import math
import base64

import requests
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

SESSION = None
_LOCK = threading.Lock()
_AUTH_COOKIES = {}  # 存储登录凭证


def set_auth(sessdata=None, bili_jct=None, dedeuserid=None):
    """设置登录凭证，支持 SESSDATA 登录方式（推荐）"""
    with _LOCK:
        global SESSION, _AUTH_COOKIES
        _AUTH_COOKIES = {}
        if sessdata:
            _AUTH_COOKIES["SESSDATA"] = sessdata
        if bili_jct:
            _AUTH_COOKIES["bili_jct"] = bili_jct
        if dedeuserid:
            _AUTH_COOKIES["DedeUserID"] = dedeuserid
        # 强制重新创建 session
        SESSION = None
        return bool(_AUTH_COOKIES)


def clear_auth():
    """清除登录凭证"""
    with _LOCK:
        global SESSION, _QR_SESSION, _AUTH_COOKIES
        _AUTH_COOKIES = {}
        SESSION = None
        _QR_SESSION = None


def get_auth_info():
    """返回当前登录状态"""
    return {
        "logged_in": "SESSDATA" in _AUTH_COOKIES and bool(_AUTH_COOKIES["SESSDATA"]),
    }


# ─── 用户名密码登录 ──────────────────────────────────────────────

# Bilibili 极验验证码的公钥 (固定)
_GEETEST_G = "1d4a5319f2e6c2a2c8c5e3b4a7d6f8e0"


def _get_login_key():
    """获取登录 RSA 公钥和 challenge"""
    ses = _get_session()
    r = ses.get(
        "https://passport.bilibili.com/x/passport-login/web/key",
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise Exception(f"获取登录密钥失败: {data.get('message', '')}")
    return data["data"]


def _get_captcha():
    """检查是否需要验证码"""
    ses = _get_session()
    import time as _time
    r = ses.get(
        "https://passport.bilibili.com/x/passport-login/captcha",
        params={
            "source": "main-web",
            "t": int(_time.time() * 1000),
        },
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        return None
    return data.get("data")


def _rsa_encrypt(password, key_str, hash_str):
    """使用 RSA 公钥加密密码"""
    key_info = RSA.import_key(key_str)
    cipher = PKCS1_v1_5.new(key_info)
    encrypted = cipher.encrypt((hash_str + password).encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def login_password(username, password):
    """用户名密码登录，成功返回 True，失败抛异常
    Bilibili 现在要求验证码（极验 Geetest），自动登录很难成功。
    推荐使用二维码扫码登录 login_qrcode_generate + login_qrcode_poll。
    """
    ses = _get_session()

    # 0. 先检查是否需要验证码
    captcha_info = _get_captcha()
    if captcha_info and captcha_info.get("geetest"):
        raise Exception(
            "B站要求验证码，用户名密码登录需要完成极验验证。\n"
            "请改用二维码扫码登录（推荐），或使用 SESSDATA Cookie 登录。"
        )

    # 1. 获取 RSA 公钥
    key_data = _get_login_key()
    rsa_key = key_data["key"]
    hash_str = key_data["hash"]

    # 2. RSA 加密密码
    encrypted_pwd = _rsa_encrypt(password, rsa_key, hash_str)

    # 3. 获取登录页面 token（csrf 校验用）
    ses.get("https://www.bilibili.com/", timeout=10)

    # 4. 提交登录
    r = ses.post(
        "https://passport.bilibili.com/x/passport-login/web/login",
        data={
            "username": username,
            "password": encrypted_pwd,
            "keep": 1,
        },
        headers={
            "Referer": "https://www.bilibili.com/",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        msg = data.get("message", "")
        code = data.get("code", 0)
        if code == -105:
            raise Exception("需要验证码。请改用二维码扫码登录或 SESSDATA Cookie 登录。")
        elif code == -629:
            raise Exception("用户名或密码错误，请检查后重试。")
        else:
            raise Exception(f"登录失败 (code={code}): {msg}")

    # 5. 提取 cookie 并保存
    cookies = {}
    for c in ses.cookies:
        cookies[c.name] = c.value
    sessdata = cookies.get("SESSDATA", "")
    bili_jct = cookies.get("bili_jct", "")
    dedeuserid = cookies.get("DedeUserID", "")
    if not sessdata:
        raise Exception("登录成功但未获取到 SESSDATA，请重试。")
    set_auth(sessdata, bili_jct, dedeuserid)
    return True


# ─── 二维码扫码登录（推荐） ──────────────────────────────────────

# QR 登录使用独立 session（不经过 _get_session，避免被 B站首页 cookie 污染）
_QR_SESSION = None


def _get_qr_session():
    global _QR_SESSION
    if _QR_SESSION is not None:
        return _QR_SESSION
    _QR_SESSION = requests.Session()
    _QR_SESSION.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/125.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    })
    return _QR_SESSION


def login_qrcode_generate():
    """生成登录二维码，返回 {qrcode_key, url}"""
    ses = _get_qr_session()
    r = ses.get(
        "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise Exception(f"生成二维码失败: {data.get('message', '')}")
    return {
        "qrcode_key": data["data"]["qrcode_key"],
        "url": data["data"]["url"],
    }


def login_qrcode_poll(qrcode_key):
    """轮询二维码扫码状态
    返回:
      {"status": "waiting"}       - 等待扫码
      {"status": "scanned"}       - 已扫码，等待确认
      {"status": "success"}       - 登录成功
      {"status": "expired"}       - 二维码已过期
      {"status": "error", "message": "..."} - 其他错误
    """
    ses = _get_qr_session()
    try:
        r = ses.get(
            "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
            params={"qrcode_key": qrcode_key},
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        return {"status": "error", "message": f"网络错误: {e}"}

    data = r.json()
    code = data.get("code")
    msg = data.get("message", "")

    if code == 0:
        # code=0 不一定表示登录成功，需要验证 data.data.url 存在 + cookie 中有 SESSDATA
        redirect_url = data.get("data", {}).get("url", "")

        # 如果 poll 返回的 data 中没有 url，说明并非真正的登录成功
        if not redirect_url:
            return {"status": "waiting", "message": msg}

        # 访问 SSO 认证 URL，跟随重定向以获取 SESSDATA cookie
        try:
            # 不自动跟随重定向，手动捕获所有 Set-Cookie
            sso_resp = ses.get(redirect_url, allow_redirects=True, timeout=10)
            # 再用 GET 访问 B站首页，确保 cookie 被 session 记录
            ses.get("https://www.bilibili.com/", timeout=10)
        except Exception:
            pass

        # 提取 cookies
        cookies = {}
        for c in ses.cookies:
            cookies[c.name] = c.value
        sessdata = cookies.get("SESSDATA", "")
        bili_jct = cookies.get("bili_jct", "")
        dedeuserid = cookies.get("DedeUserID", "")

        if not sessdata:
            return {"status": "error", "message": "扫码成功但未获取到 SESSDATA，请检查网络环境或重试"}

        set_auth(sessdata, bili_jct, dedeuserid)
        return {"status": "success", "message": "登录成功"}
    elif code == 86101:
        return {"status": "waiting", "message": msg}
    elif code == 86090:
        return {"status": "scanned", "message": msg}
    elif code == 86038:
        return {"status": "expired", "message": msg}
    else:
        return {"status": "error", "message": f"轮询异常 (code={code}): {msg}"}


# ─── SESSDATA 直接登录（从浏览器复制 Cookie） ───────────────────

def login_sessdata(sessdata, bili_jct=None, dedeuserid=None):
    """使用 SESSDATA Cookie 登录（无需验证码）
    用户可以手动从浏览器 DevTools 中复制 SESSDATA 值来登录。
    """
    if not sessdata or not sessdata.strip():
        raise Exception("SESSDATA 不能为空")

    # 清理可能的空白和引号
    sessdata = sessdata.strip().strip('"').strip("'")

    # 验证 SESSDATA 是否有效
    with _LOCK:
        global SESSION, _AUTH_COOKIES
        _AUTH_COOKIES = {"SESSDATA": sessdata}
        if bili_jct:
            _AUTH_COOKIES["bili_jct"] = bili_jct.strip().strip('"').strip("'")
        if dedeuserid:
            _AUTH_COOKIES["DedeUserID"] = str(dedeuserid).strip().strip('"').strip("'")
        SESSION = None  # 强制重建 session

    # 用新 cookie 发请求验证
    try:
        ses = _get_session()
        r = ses.get(
            "https://api.bilibili.com/x/web-interface/nav",
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            clear_auth()
            raise Exception(f"Cookie 验证失败: {data.get('message', 'SESSDATA 可能已过期')}")
        nav = data.get("data", {})
        if not nav.get("isLogin"):
            clear_auth()
            raise Exception("Cookie 验证失败: 未登录状态，SESSDATA 可能已过期。请重新从浏览器获取。")
        print(f"[bili_dl] SESSDATA 登录成功: {nav.get('uname', '未知用户')}")
        return True
    except requests.RequestException:
        clear_auth()
        raise Exception("Cookie 验证失败: 网络错误。请检查网络后重试。")


def _get_session():
    global SESSION
    if SESSION is not None:
        return SESSION
    SESSION = requests.Session()
    SESSION.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/125.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    })
    # 注入登录 cookie
    if _AUTH_COOKIES:
        for k, v in _AUTH_COOKIES.items():
            SESSION.cookies.set(k, v, domain=".bilibili.com")
    SESSION.get("https://www.bilibili.com/", timeout=10)
    return SESSION


# 当前目录下的 ffmpeg.exe（本项目自带）
_FFMPEG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")


def _find_ffmpeg():
    """查找 ffmpeg 可执行文件路径"""
    # 1. 优先用项目自带的 ffmpeg.exe
    if os.path.exists(_FFMPEG_PATH):
        return _FFMPEG_PATH
    # 2. 检查 bili_dl.py 同目录
    _dir = os.path.dirname(os.path.abspath(__file__))
    _local = os.path.join(_dir, "ffmpeg.exe")
    if os.path.exists(_local):
        return _local
    # 3. 系统 PATH 中的 ffmpeg
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        if r.returncode == 0:
            return "ffmpeg"
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    # 4. Windows where
    try:
        r = subprocess.run(["where", "ffmpeg"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().split("\n")[0]
    except Exception:
        pass
    return None


def ensure_ffmpeg():
    """检查 ffmpeg，没有则提示安装"""
    path = _find_ffmpeg()
    if path:
        return path
    print("=" * 50)
    print(" ffmpeg 未安装！")
    print(f" 请将 ffmpeg.exe 放在 {os.path.dirname(os.path.abspath(__file__))} 目录下")
    print(" 或从 https://ffmpeg.org/download.html 下载")
    print("=" * 50)
    return None


def extract_bvid(url):
    m = re.search(r"BV\w+", url)
    return m.group(0) if m else None


def get_video_info(url):
    """通过 Bilibili API 获取视频信息"""
    bvid = extract_bvid(url)
    if not bvid:
        raise ValueError("无法从链接中解析出 BV 号")

    ses = _get_session()
    r = ses.get(
        "https://api.bilibili.com/x/web-interface/view",
        params={"bvid": bvid}, timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise Exception(f"API 错误: {data.get('message', '未知错误')}")

    v = data["data"]
    return {
        "title": v.get("title", ""),
        "duration": v.get("duration", 0),
        "uploader": v.get("owner", {}).get("name", ""),
        "uploader_uid": v.get("owner", {}).get("mid", 0),
        "thumbnail": v.get("pic", ""),
        "description": (v.get("desc") or "")[:200],
        "bvid": bvid,
        "aid": v.get("aid", 0),
        "cid": v.get("cid", 0),
        "pages": [
            {"title": p.get("part", ""), "cid": p.get("cid", 0)}
            for p in v.get("pages", [])
        ],
    }


# qn 值映射
QN_MAP = {
    "360p": 16,
    "480p": 32,
    "720p": 64,
    "720p60": 74,
    "1080p": 80,
    "1080p60": 116,
    "4K": 120,
    "best": 127,
}


def get_play_info(bvid, cid, qn=127):
    """获取播放信息（视频流地址）"""
    ses = _get_session()
    r = ses.get(
        "https://api.bilibili.com/x/player/playurl",
        params={
            "bvid": bvid,
            "cid": cid,
            "qn": qn,
            "fnval": 4048,
            "fourk": 1,
        },
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise Exception(f"播放 API 错误: {data.get('message', '')}")
    return data["data"]


def _download_stream(url, filepath, referer, on_progress=None, cancel_flag=None):
    """下载一个流到文件，支持进度回调"""
    ses = _get_session()
    headers = {"Referer": referer}
    resp = ses.get(url, headers=headers, stream=True, timeout=30)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    chunk_size = 1024 * 1024  # 1MB

    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if cancel_flag and cancel_flag():
                f.close()
                os.remove(filepath)
                raise Exception("已取消")
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress and total:
                    on_progress(min(downloaded / total, 1.0))


def download(url, output_dir, quality="best", on_progress=None, cancel_flag=None):
    """下载视频，返回 (成功, 文件路径/错误)"""
    os.makedirs(output_dir, exist_ok=True)
    bvid = extract_bvid(url)
    if not bvid:
        return False, "无法解析 BV 号"

    ffmpeg_path = ensure_ffmpeg()
    print(f"[bili_dl] _FFMPEG_PATH={_FFMPEG_PATH}", flush=True)
    print(f"[bili_dl] find_ffmpeg result={ffmpeg_path}", flush=True)
    print(f"[bili_dl] CWD={os.getcwd()}", flush=True)
    print(f"[bili_dl] __file__={__file__}", flush=True)
    print(f"[bili_dl] exists(ffmpeg)={os.path.exists(_FFMPEG_PATH)}", flush=True)
    if not ffmpeg_path:
        return False, ("未找到 ffmpeg，请安装: "
                       "https://ffmpeg.org/download.html 或 winget install ffmpeg")

    try:
        info = get_video_info(url)
    except Exception as e:
        return False, f"获取视频信息失败: {e}"

    title = info["title"]
    # 清理文件名
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title).strip()
    if not safe_title:
        safe_title = bvid

    qn = QN_MAP.get(quality, QN_MAP["best"])
    cid = info["cid"]

    try:
        play = get_play_info(bvid, cid, qn)
    except Exception as e:
        return False, f"获取播放地址失败: {e}"

    referer = f"https://www.bilibili.com/video/{bvid}"

    # 判断是否为 DASH
    if "dash" in play and play["dash"].get("video"):
        # DASH: 视频和音频分离
        dash = play["dash"]
        videos = dash["video"]
        audios = dash.get("audio", [])

        if not videos:
            return False, "未找到视频流"
        if not audios:
            return False, "未找到音频流"

        # 选最高画质视频流
        video_stream = videos[0]
        for v in videos:
            if v.get("id", 0) > video_stream.get("id", 0):
                video_stream = v

        # 选最高音质音频流
        audio_stream = audios[0] if audios else None
        for a in audios:
            if a.get("bandwidth", 0) > audio_stream.get("bandwidth", 0):
                audio_stream = a

        video_url = video_stream.get("baseUrl") or video_stream.get("base_url", "")
        audio_url = audio_stream.get("baseUrl") or audio_stream.get("base_url", "")

        if not video_url or not audio_url:
            return False, "获取流地址失败"

        tmp_dir = os.path.join(output_dir, f".tmp_{bvid}")
        os.makedirs(tmp_dir, exist_ok=True)
        video_file = os.path.join(tmp_dir, "video.m4s")
        audio_file = os.path.join(tmp_dir, "audio.m4s")

        try:
            # 下载视频流
            if on_progress:
                on_progress(0.0, "下载视频流...")

            _download_stream(video_url, video_file, referer,
                             cancel_flag=cancel_flag)

            if on_progress:
                on_progress(0.4, "下载音频流...")

            _download_stream(audio_url, audio_file, referer,
                             cancel_flag=cancel_flag)

            if on_progress:
                on_progress(0.7, "合并视频+音频...")

            # ffmpeg 合并
            ext = ".mp4"
            output_file = os.path.join(output_dir, f"{safe_title}{ext}")

            ffmpeg_cmd = [
                ffmpeg_path, "-y",
                "-i", video_file,
                "-i", audio_file,
                "-c:v", "copy",
                "-c:a", "copy",
                "-movflags", "+faststart",
                output_file,
            ]

            result = subprocess.run(
                ffmpeg_cmd, capture_output=True, text=False, timeout=300,
            )
            if result.returncode != 0:
                err = result.stderr.decode("utf-8", errors="replace")[:300]
                return False, f"ffmpeg 合并失败: {err}"

            if on_progress:
                on_progress(1.0)

            return True, output_file

        finally:
            # 清理临时文件
            for f in [video_file, audio_file]:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                    os.rmdir(tmp_dir)
                except OSError:
                    pass

    elif play.get("durl"):
        # 非 DASH: 单个视频流
        durls = play["durl"]
        best_url = durls[0].get("url", "")

        if not best_url:
            return False, "获取流地址失败"

        tmp_dir = os.path.join(output_dir, f".tmp_{bvid}")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_file = os.path.join(tmp_dir, "source.mp4")

        try:
            if on_progress:
                on_progress(0.0, "下载中...")

            _download_stream(best_url, tmp_file, referer,
                             cancel_flag=cancel_flag)

            if on_progress:
                on_progress(0.8, "封装中...")

            ext = ".mp4"
            output_file = os.path.join(output_dir, f"{safe_title}{ext}")

            ffmpeg_cmd = [
                ffmpeg_path, "-y",
                "-i", tmp_file,
                "-c", "copy",
                "-movflags", "+faststart",
                output_file,
            ]
            subprocess.run(ffmpeg_cmd, capture_output=True, timeout=120)

            if on_progress:
                on_progress(1.0)

            return True, output_file

        finally:
            try:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
                os.rmdir(tmp_dir)
            except OSError:
                pass

    return False, "无法解析视频格式"

def list_formats(url):
    """列出可用格式（简单提示）"""
    info = get_video_info(url)
    title = info["title"]
    duration = info["duration"]
    lines = [
        f"标题: {title}",
        f"时长: {duration} 秒",
        f"UP主: {info['uploader']}",
        f"BV号: {info['bvid']}",
        "",
        "可用画质:",
        "  best   - 最高画质",
        "  4K     - 2160P",
        "  1080p  - 1080P",
        "  1080p60- 1080P 60帧",
        "  720p   - 720P",
        "  480p   - 480P",
        "  360p   - 360P",
        "  audio  - 仅音频 (暂不支持)",
    ]
    return "\n".join(lines)
