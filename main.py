"""
Crucible Upload UI — Flask backend
"""
import logging
import queue
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog

from flask import Flask, jsonify, render_template, request

import prefect_backend as backend
from instrument_conf import DEFAULT_BROWSE_DIR, IS_SESSION, DEFAULT_INSTRUMENT_NAME, PRINT_BARCODE_ENABLED, INSTRUMENTS, INSTRUMENT_FLOWS

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(funcName)s: %(message)s")

app = Flask(__name__)

# Tkinter must run on the main thread. Flask runs in a background thread.
# We use two queues to hand off dialog requests/results between threads.
_tk_root = tk.Tk()
_tk_root.withdraw()
_tk_root.wm_attributes("-topmost", 1)

_browse_request: queue.Queue = queue.Queue()
_browse_result: queue.Queue = queue.Queue()


def _check_browse_queue():
    """Called repeatedly on the main thread via tkinter's event loop."""
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
    # Signal the main thread to open the dialog, then wait for the result.
    _browse_request.put(True)
    path = _browse_result.get(timeout=60)
    return jsonify({"path": path})


@app.post("/api/user/lookup")
def user_lookup():
    email = (request.json or {}).get("email", "").strip()
    if not email:
        return jsonify({"error": "email required"}), 400
    try:
        result = backend.lookup_user_by_email(email)
        backend.logger.info(f"Lookup for email '{email}' returned: {result}")
    except Exception as e:
        backend.logger.error(e)
        return jsonify({"error": str(e)}), 500
    if not result:
        backend.logger.info(f"No user found for email '{email}'")
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
    try:
        result = backend.lookup_sample(
            sample_name=sample_name,
            sample_unique_id=sample_unique_id,
            project_id=project_id,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if not result:
        return jsonify({"error": "No sample found"}), 404
    return jsonify(result)


@app.post("/api/sample/print-barcode")
def print_barcode():
    data = request.json or {}
    sample_unique_id = data.get("sample_unique_id", "").strip()
    sample_name = data.get("sample_name", "").strip()
    if not sample_unique_id:
        return jsonify({"error": "Missing sample_unique_id"}), 400
    try:
        backend.print_sample_barcode(sample_unique_id, sample_name)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.post("/api/upload")
def do_upload():
    data = request.json or {}
    required = ["orcid", "project_id", "instrument_name", "session_folder_path"]
    missing = [f for f in required if not data.get(f, "").strip()]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    orcid = data["orcid"].strip()
    project_id = data["project_id"].strip()
    instrument_name = data["instrument_name"].strip()
    sample_unique_id = data.get("sample_unique_id", None)
    session_folder_path = data["session_folder_path"].strip()
    comments = data.get("comments", "").strip()
    kw_list = []

    # Look up the Prefect deployment for this instrument
    deployment_name = INSTRUMENT_FLOWS.get(instrument_name)
    if not deployment_name:
        return jsonify({"error": f"No upload flow configured for instrument '{instrument_name}'"}), 400

    try:
        from prefect.deployments import run_deployment
        flow_run = run_deployment(
            deployment_name,
            parameters={
                "file": session_folder_path,
                "instrument_name": instrument_name,
                "project_id": project_id,
                "orcid": orcid,
                "sample_unique_id": sample_unique_id,
                "kw_list": kw_list,
                "comments": comments,
            },
            timeout=0,  # return immediately, monitor in Prefect UI
        )
        return jsonify({"flow_run_id": str(flow_run.id), "project_id": project_id})
    except Exception as e:
        backend.logger.error(e)
        return jsonify({"error": str(e)}), 500


@app.get("/api/flow-run/<flow_run_id>")
def flow_run_status(flow_run_id):
    from prefect.client.orchestration import get_client
    from pathlib import Path
    import asyncio

    async def _get_status():
        async with get_client() as prefect_client:
            flow_run = await prefect_client.read_flow_run(flow_run_id)
            return {
                "status": flow_run.state.type.value,
                "name": flow_run.state.name,
            }

    try:
        result = asyncio.run(_get_status())
        # Read persisted result from shared file
        result_file = Path(".flow_results") / flow_run_id
        if result_file.exists():
            result["result"] = result_file.read_text()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Flask runs in a daemon thread; tkinter mainloop holds the main thread.
    flask_thread = threading.Thread(
        target=lambda: app.run(debug=False, port=5000), daemon=True
    )
    flask_thread.start()
    webbrowser.open("http://localhost:5000")
    _tk_root.after(50, _check_browse_queue)
    _tk_root.mainloop()
