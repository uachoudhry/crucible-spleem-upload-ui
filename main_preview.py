"""
Preview-only launcher — runs the UI with a mock backend (no Crucible/Prefect needed).
Usage: uv run python main_preview.py
"""
import logging
import queue
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog

from flask import Flask, jsonify, render_template, request

import mock_backend as backend
from instrument_conf import DEFAULT_BROWSE_DIR, IS_SESSION, DEFAULT_INSTRUMENT_NAME, PRINT_BARCODE_ENABLED, INSTRUMENTS

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(funcName)s: %(message)s")

app = Flask(__name__)

_tk_root = tk.Tk()
_tk_root.withdraw()
_tk_root.wm_attributes("-topmost", 1)

_browse_request: queue.Queue = queue.Queue()
_browse_result: queue.Queue = queue.Queue()


def _check_browse_queue():
    try:
        _browse_request.get_nowait()
        if IS_SESSION:
            kwargs = {"master": _tk_root, "title": "Select session folder"}
            if DEFAULT_BROWSE_DIR:
                kwargs["initialdir"] = DEFAULT_BROWSE_DIR
            path = filedialog.askdirectory(**kwargs)
        else:
            kwargs = {"master": _tk_root, "title": "Select file"}
            if DEFAULT_BROWSE_DIR:
                kwargs["initialdir"] = DEFAULT_BROWSE_DIR
            path = filedialog.askopenfilename(**kwargs)
        _browse_result.put(path or "")
    except queue.Empty:
        pass
    _tk_root.after(50, _check_browse_queue)


@app.get("/")
def index():
    return render_template("index.html", print_barcode_enabled=PRINT_BARCODE_ENABLED)


@app.get("/api/instruments")
def get_instruments():
    return jsonify({"instruments": INSTRUMENTS, "default": DEFAULT_INSTRUMENT_NAME})


@app.get("/api/browse")
def browse():
    _browse_request.put(True)
    path = _browse_result.get(timeout=60)
    return jsonify({"path": path})


@app.post("/api/user/lookup")
def user_lookup():
    email = (request.json or {}).get("email", "").strip()
    if not email:
        return jsonify({"error": "email required"}), 400
    result = backend.lookup_user_by_email(email)
    if not result:
        return jsonify({"error": f"No user found for '{email}'"}), 404
    return jsonify(result)


@app.post("/api/sample/lookup")
def sample_lookup():
    data = request.json or {}
    sample_name = data.get("sample_name") or None
    sample_unique_id = data.get("sample_unique_id") or None
    project_id = data.get("project_id") or None
    if not sample_name and not sample_unique_id:
        return jsonify({"error": "sample_name or sample_unique_id required"}), 400
    result = backend.lookup_sample(sample_name=sample_name, sample_unique_id=sample_unique_id, project_id=project_id)
    if not result:
        return jsonify({"error": "No sample found"}), 404
    return jsonify(result)


@app.post("/api/sample/create")
def sample_create():
    data = request.json or {}
    sample_name = (data.get("sample_name") or "").strip()
    owner_orcid = (data.get("owner_orcid") or "").strip()
    project_id = (data.get("project_id") or "").strip()
    if not sample_name or not owner_orcid or not project_id:
        return jsonify({"error": "sample_name, owner_orcid, and project_id are required"}), 400
    result = backend.create_sample(sample_name=sample_name, owner_orcid=owner_orcid, project_id=project_id)
    return jsonify(result)


@app.post("/api/sample/print-barcode")
def print_barcode():
    data = request.json or {}
    sample_unique_id = data.get("sample_unique_id", "").strip()
    sample_name = data.get("sample_name", "").strip()
    if not sample_unique_id:
        return jsonify({"error": "Missing sample_unique_id"}), 400
    backend.print_sample_barcode(sample_unique_id, sample_name)
    return jsonify({"ok": True})


@app.post("/api/session/check")
def session_check():
    data = request.json or {}
    required = ["orcid", "project_id", "instrument_name", "session_folder_path"]
    missing = [f for f in required if not (data.get(f) or "").strip()]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    sessions = backend.check_existing_sessions(
        session_folder_path=data["session_folder_path"].strip(),
        orcid=data["orcid"].strip(),
        project_id=data["project_id"].strip(),
        instrument_name=data["instrument_name"].strip(),
    )
    return jsonify({"sessions": sessions})


@app.post("/api/upload")
def do_upload():
    return jsonify({"flow_run_id": "mock-flow-run-001", "project_id": "mock-project"})


@app.get("/api/flow-run/<flow_run_id>")
def flow_run_status(flow_run_id):
    return jsonify({"status": "COMPLETED", "name": "mock-run"})


if __name__ == "__main__":
    flask_thread = threading.Thread(
        target=lambda: app.run(debug=False, port=5000), daemon=True
    )
    flask_thread.start()
    webbrowser.open("http://localhost:5000")
    _tk_root.after(50, _check_browse_queue)
    _tk_root.mainloop()
