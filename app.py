#!/usr/bin/env python3
"""
视频下载服务 - 统一入口
自动识别视频来源（Bilibili / Twitter X），分发到对应下载引擎
"""

import os
import sys
import threading

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# 确保 stdout 支持 utf-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = BASE_DIR + os.pathsep + os.environ.get("PATH", "")

app = Flask(__name__, static_folder="static")
CORS(app)

DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ─── 导入子模块 ──────────────────────────────────────────────────

from bili import bili_dl
from twitter import x_dl
from youtube import yt_dl


def detect_source(url):
    """判断视频来源，返回 'bili', 'twitter', 'youtube', 或 None"""
    url_lower = url.strip().lower()
    if "bilibili.com" in url_lower or "b23.tv" in url_lower:
        return "bili"
    if "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    return None


# ─── Bilibili 登录 ──────────────────────────────────────────────


@app.route("/api/login/status")
def api_login_status():
    return jsonify(bili_dl.get_auth_info())


@app.route("/api/login/password", methods=["POST"])
def api_login_password():
    data = request.get_json()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "")
    if not username or not password:
        return jsonify({"error": "请输入用户名和密码"}), 400
    try:
        bili_dl.login_password(username, password)
        return jsonify({"ok": True, "message": "登录成功"})
    except Exception as e:
        return jsonify({"error": str(e)}), 401


@app.route("/api/login/qrcode/generate")
def api_login_qrcode_generate():
    try:
        result = bili_dl.login_qrcode_generate()
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/login/qrcode/poll")
def api_login_qrcode_poll():
    qrcode_key = request.args.get("qrcode_key", "").strip()
    if not qrcode_key:
        return jsonify({"error": "缺少 qrcode_key"}), 400
    try:
        result = bili_dl.login_qrcode_poll(qrcode_key)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/login/sessdata", methods=["POST"])
def api_login_sessdata():
    data = request.get_json()
    sessdata = (data.get("sessdata") or "").strip()
    bili_jct = (data.get("bili_jct") or "").strip()
    dedeuserid = (data.get("dedeuserid") or "").strip()
    if not sessdata:
        return jsonify({"error": "请输入 SESSDATA"}), 400
    try:
        bili_dl.login_sessdata(sessdata, bili_jct, dedeuserid)
        return jsonify({"ok": True, "message": "Cookie 登录成功"})
    except Exception as e:
        return jsonify({"error": str(e)}), 401


@app.route("/api/login/logout")
def api_login_logout():
    bili_dl.clear_auth()
    return jsonify({"ok": True, "message": "已退出登录"})


# ─── YouTube 登录 ──────────────────────────────────────────────

@app.route("/api/yt/login/status")
def api_yt_login_status():
    return jsonify(yt_dl.get_login_status())


@app.route("/api/yt/login/browser", methods=["POST"])
def api_yt_login_browser():
    """从指定浏览器提取 YouTube cookies"""
    data = request.get_json()
    browser = (data.get("browser") or "").strip()
    if not browser:
        return jsonify({"error": "请选择浏览器"}), 400
    try:
        result = yt_dl.login_browser(browser)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/yt/login/auto")
def api_yt_login_auto():
    """自动遍历所有浏览器提取 cookie"""
    try:
        result = yt_dl.auto_extract_cookies()
        if result["ok"]:
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/yt/login/browsers")
def api_yt_list_browsers():
    """列出支持提取 cookie 的浏览器"""
    try:
        browsers = yt_dl.list_browsers()
        return jsonify({"browsers": browsers})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/yt/login/logout")
def api_yt_login_logout():
    yt_dl.logout()
    return jsonify({"ok": True, "message": "已退出 YouTube 登录"})


@app.route("/api/yt/login/open", methods=["POST"])
def api_yt_login_open():
    """在用户默认浏览器中打开 YouTube 登录页面"""
    try:
        yt_dl.open_youtube_login()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Twitter/X 登录 API ──────────────────────────────

@app.route("/api/x/login/status")
def api_x_login_status():
    return jsonify(x_dl.get_login_status())


@app.route("/api/x/login/auto")
def api_x_login_auto():
    """自动遍历所有浏览器提取 Twitter cookie"""
    try:
        result = x_dl.auto_extract_cookies()
        if result["ok"]:
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/x/login/browsers")
def api_x_list_browsers():
    """列出支持提取 cookie 的浏览器"""
    try:
        browsers = x_dl.list_browsers()
        return jsonify({"browsers": browsers})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/x/login/logout")
def api_x_login_logout():
    x_dl.logout()
    return jsonify({"ok": True, "message": "已退出 Twitter 登录"})


@app.route("/api/x/login/open", methods=["POST"])
def api_x_login_open():
    """在用户默认浏览器中打开 Twitter 登录页面"""
    try:
        x_dl.open_twitter_login()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── 获取视频信息（自动检测来源） ──────────────────────────────

@app.route("/api/info", methods=["POST"])
def api_info():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "请输入视频链接"}), 400

    source = detect_source(url)
    if not source:
        return jsonify({"error": "不支持的链接，目前支持 Bilibili、Twitter/X、YouTube"}), 400

    try:
        if source == "bili":
            info = bili_dl.get_video_info(url)
            info["source"] = "bili"
        elif source == "twitter":
            info = x_dl.get_video_info(url)
            info["source"] = "twitter"
        elif source == "youtube":
            info = yt_dl.get_video_info(url)
            info["source"] = "youtube"
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── 格式列表 ──────────────────────────────────────────────────

@app.route("/api/formats", methods=["POST"])
def api_formats():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "请输入视频链接"}), 400

    source = detect_source(url)
    try:
        if source == "bili":
            formats = bili_dl.list_formats(url)
            return jsonify({"formats": formats})
        elif source in ("twitter", "youtube"):
            dl = x_dl if source == "twitter" else yt_dl
            info = dl.get_video_info(url)
            lines = [
                f"标题: {info['title']}",
                f"上传者: {info['uploader']}",
                f"时长: {info['duration']} 秒",
                "", "可用格式:",
            ]
            for f in info.get("formats", []):
                size = f.get("filesize") or 0
                size_str = f"{round(size / 1024 / 1024, 1)}MB" if size else "?"
                lines.append(f"  {f['format_id']:>6} | {f['ext']:>4} | {f['resolution']:>12} | {size_str}")
            return jsonify({"formats": "\n".join(lines)})
        else:
            return jsonify({"error": "不支持的链接"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── 下载（自动检测来源） ──────────────────────────────────────

tasks = {}
task_id_counter = 0


@app.route("/api/download", methods=["POST"])
def api_download():
    global task_id_counter
    data = request.get_json()
    url = (data.get("url") or "").strip()
    quality = data.get("quality", "best")
    output_dir = data.get("output_dir", "").strip()

    if not url:
        return jsonify({"error": "请输入视频链接"}), 400

    source = detect_source(url)
    if not source:
        return jsonify({"error": "不支持的链接"}), 400

    if output_dir:
        download_dir = output_dir
    else:
        download_dir = DOWNLOAD_DIR

    task_id_counter += 1
    tid = str(task_id_counter)
    tasks[tid] = {"status": "running", "progress": 0, "message": "准备中...", "result": None, "error": None}

    def worker(tid, url, quality, download_dir):
        try:
            os.environ["PATH"] = BASE_DIR + os.pathsep + os.environ.get("PATH", "")

            def on_progress(pct, msg=None):
                tasks[tid]["progress"] = round(pct * 100)
                tasks[tid]["message"] = msg if msg else f"{round(pct * 100)}%"

            if source == "bili":
                success, result = bili_dl.download(url, download_dir, quality, on_progress=on_progress)
            elif source == "twitter":
                success, result = x_dl.download(url, download_dir, quality, on_progress=on_progress)
            elif source == "youtube":
                success, result = yt_dl.download(url, download_dir, quality, on_progress=on_progress)

            if success:
                tasks[tid]["status"] = "completed"
                tasks[tid]["result"] = result
                tasks[tid]["progress"] = 100
                tasks[tid]["message"] = "下载完成"
            else:
                tasks[tid]["status"] = "failed"
                tasks[tid]["error"] = result
                tasks[tid]["message"] = "下载失败"
        except Exception as e:
            tasks[tid]["status"] = "failed"
            tasks[tid]["error"] = str(e)
            tasks[tid]["message"] = "异常错误"

    t = threading.Thread(target=worker, args=(tid, url, quality, download_dir), daemon=True)
    t.start()

    return jsonify({"task_id": tid})


@app.route("/api/task/<task_id>")
def api_task_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(task)


# ─── 首页 ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    print(f"下载目录: {DOWNLOAD_DIR}")
    print(f"服务地址: http://127.0.0.1:5000")
    import webbrowser
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
