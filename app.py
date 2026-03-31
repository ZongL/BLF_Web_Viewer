"""
Flask server for BLF Parser Web Tool.

Provides API routes for uploading BLF/DBC files, parsing CAN messages,
and retrieving decoded signal time-series data.
"""

import os
import time
import uuid
import threading
import webbrowser
from pathlib import Path

from flask import Flask, request, jsonify, redirect

from parser import parse_blf, get_signal_data

app = Flask(__name__, static_folder="static", static_url_path="/static")

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# In-memory session store: {session_id: {data, created_at}}
sessions = {}
SESSION_TTL = 30 * 60  # 30 minutes

# In-memory progress store: {session_id: {phase, current, total, error}}
progress_store = {}

# Max upload size: 500 MB
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024


def _gc_sessions():
    """Remove sessions older than SESSION_TTL."""
    now = time.time()
    expired = [sid for sid, s in sessions.items() if now - s["created_at"] > SESSION_TTL]
    for sid in expired:
        # Clean up uploaded files
        session_dir = UPLOAD_DIR / sid
        if session_dir.exists():
            for f in session_dir.iterdir():
                f.unlink()
            session_dir.rmdir()
        del sessions[sid]
        progress_store.pop(sid, None)


@app.route("/")
def index():
    return redirect("/static/index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    _gc_sessions()

    # Validate files
    if "blf_file" not in request.files:
        return jsonify({"error": "No BLF file provided"}), 400

    blf_file = request.files["blf_file"]
    dbc_files = request.files.getlist("dbc_files")

    if not blf_file.filename:
        return jsonify({"error": "No BLF file selected"}), 400
    if not blf_file.filename.lower().endswith(".blf"):
        return jsonify({"error": "File must be a .blf file"}), 400
    if not dbc_files or not dbc_files[0].filename:
        return jsonify({"error": "No DBC file(s) provided"}), 400
    for dbc in dbc_files:
        if not dbc.filename.lower().endswith(".dbc"):
            return jsonify({"error": f"File '{dbc.filename}' is not a .dbc file"}), 400

    # Save files
    session_id = str(uuid.uuid4())
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(exist_ok=True)

    blf_path = session_dir / blf_file.filename
    blf_file.save(str(blf_path))

    dbc_paths = []
    for dbc in dbc_files:
        dbc_path = session_dir / dbc.filename
        dbc.save(str(dbc_path))
        dbc_paths.append(dbc_path)

    # Initialize progress
    progress_store[session_id] = {
        "phase": "uploading",
        "current": 0,
        "total": 0,
        "error": None,
        "done": False,
    }

    # Parse in background thread
    def _parse():
        def on_progress(phase, current, total):
            progress_store[session_id].update({
                "phase": phase,
                "current": current,
                "total": total,
            })

        try:
            parsed = parse_blf(blf_path, dbc_paths, progress_cb=on_progress)

            # Cache session
            sessions[session_id] = {
                "data": parsed,
                "created_at": time.time(),
            }

            progress_store[session_id].update({
                "phase": "done",
                "done": True,
                "result": {
                    "session_id": session_id,
                    "summary": parsed["summary"],
                    "signals": parsed["signal_list"],
                    "undecoded_ids": parsed["undecoded_ids"],
                },
            })
        except Exception as e:
            progress_store[session_id].update({
                "phase": "error",
                "error": str(e),
                "done": True,
            })
        finally:
            # Clean up uploaded files
            if session_dir.exists():
                for f in session_dir.iterdir():
                    f.unlink()
                session_dir.rmdir()

    threading.Thread(target=_parse, daemon=True).start()

    return jsonify({"session_id": session_id})


@app.route("/api/progress/<session_id>")
def get_progress(session_id):
    info = progress_store.get(session_id)
    if not info:
        return jsonify({"error": "Session not found"}), 404

    resp = {
        "phase": info["phase"],
        "current": info["current"],
        "total": info["total"],
        "done": info["done"],
        "error": info["error"],
    }

    # Include result when done
    if info["done"] and not info["error"] and "result" in info:
        resp["result"] = info["result"]

    return jsonify(resp)


@app.route("/api/signals", methods=["POST"])
def signals():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    session_id = data.get("session_id")
    signal_keys = data.get("signals", [])
    max_points = data.get("max_points", 5000)

    if not session_id or session_id not in sessions:
        return jsonify({"error": "Session not found or expired"}), 404

    if not signal_keys:
        return jsonify({"error": "No signals selected"}), 400

    # Refresh session timestamp
    sessions[session_id]["created_at"] = time.time()

    result = get_signal_data(sessions[session_id]["data"], signal_keys, max_points)

    return jsonify({"signals": result})


PORT = 8080


def open_browser():
    """Open browser after a short delay to let the server start."""
    time.sleep(1.0)
    webbrowser.open(f"http://localhost:{PORT}")


if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    print(f"BLF Parser running at http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
