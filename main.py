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
from ai_services import voice_bp, extract_keywords

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(funcName)s: %(message)s")

app = Flask(__name__)
app.register_blueprint(voice_bp)

# Tkinter must run on the main thread. Flask runs in a background thread.
# We use two queues to hand off dialog requests/results between threads.
_tk_root = tk.Tk()
_tk_root.withdraw()
_tk_root.wm_attributes("-topmost", 1)

_browse_request: queue.Queue = queue.Queue()
_browse_result: queue.Queue = queue.Queue()


def _check_browse_queue():
    """Called repeatedly on the main thread via tkinter's event loop.
    Always returns a list of paths via _browse_result so the API has a uniform shape.
    """
    try:
        _browse_request.get_nowait()
        if IS_SESSION:
            kwargs = {"master": _tk_root, "title": "Select session folder"}
            if DEFAULT_BROWSE_DIR:
                kwargs["initialdir"] = DEFAULT_BROWSE_DIR
            path = filedialog.askdirectory(**kwargs)
            paths = [path] if path else []
        else:
            kwargs = {"master": _tk_root, "title": "Select file(s)"}
            if DEFAULT_BROWSE_DIR:
                kwargs["initialdir"] = DEFAULT_BROWSE_DIR
            paths = list(filedialog.askopenfilenames(**kwargs))
        _browse_result.put(paths)
    except queue.Empty:
        pass
    _tk_root.after(50, _check_browse_queue)


@app.get("/")
def index():
    return render_template("index.html", print_barcode_enabled=PRINT_BARCODE_ENABLED)


@app.get("/api/instruments")
def get_instruments():
    return jsonify({
        "instruments": INSTRUMENTS,
        "default": DEFAULT_INSTRUMENT_NAME,
        "is_session": IS_SESSION,
    })


@app.get("/api/browse")
def browse():
    # Signal the main thread to open the dialog, then wait for the result.
    _browse_request.put(True)
    paths = _browse_result.get(timeout=60)
    return jsonify({"paths": paths})


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


@app.post("/api/sample/create")
def sample_create():
    data = request.json or {}
    sample_name = (data.get("sample_name") or "").strip()
    owner_orcid = (data.get("owner_orcid") or "").strip()
    project_id = (data.get("project_id") or "").strip()
    if not sample_name or not owner_orcid or not project_id:
        return jsonify({"error": "sample_name, owner_orcid, and project_id are required"}), 400
    try:
        result = backend.create_sample(
            sample_name=sample_name,
            owner_orcid=owner_orcid,
            project_id=project_id,
            description=data.get("description") or None,
            sample_type=data.get("sample_type") or None,
        )
    except Exception as e:
        backend.logger.error(e)
        return jsonify({"error": str(e)}), 500
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


@app.post("/api/session/check")
def session_check():
    data = request.json or {}
    required = ["orcid", "project_id", "instrument_name", "session_folder_path"]
    missing = [f for f in required if not (data.get(f) or "").strip()]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    try:
        sessions = backend.check_existing_sessions(
            session_folder_path=data["session_folder_path"].strip(),
            orcid=data["orcid"].strip(),
            project_id=data["project_id"].strip(),
            instrument_name=data["instrument_name"].strip(),
        )
    except Exception as e:
        backend.logger.error(e)
        return jsonify({"error": str(e)}), 500
    return jsonify({"sessions": sessions})


@app.post("/api/upload")
def do_upload():
    data = request.json or {}
    required = ["orcid", "project_id", "instrument_name"]
    missing = [f for f in required if not (data.get(f) or "").strip()]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    orcid = data["orcid"].strip()
    project_id = data["project_id"].strip()
    instrument_name = data["instrument_name"].strip()
    sample_unique_id = data.get("sample_unique_id", None)
    session_dsid = data.get("session_dsid", None)
    comments = data.get("comments", "").strip()
    kw_list = data.get("keywords", []) or extract_keywords(comments, instrument_name)

    # Non-session mode: caller sends a list of file paths; session mode: a single folder path.
    if IS_SESSION:
        session_folder_path = (data.get("session_folder_path") or "").strip()
        if not session_folder_path:
            return jsonify({"error": "Missing field: session_folder_path"}), 400
    else:
        session_folder_paths = data.get("session_folder_paths") or []
        if not session_folder_paths:
            return jsonify({"error": "Missing field: session_folder_paths"}), 400

    from prefect.deployments import run_deployment

    if IS_SESSION:
        # Session mode — existing behavior. Create parent session record sync so
        # the UI can show the Crucible link + QR before the flow runs.
        deployment_name = INSTRUMENT_FLOWS.get(instrument_name)
        if not deployment_name:
            return jsonify({"error": f"No upload flow configured for instrument '{instrument_name}'"}), 400
        try:
            _, dsid = backend.create_session(
                session_folder_path=session_folder_path,
                kw_list=kw_list,
                comments=comments,
                orcid=orcid,
                project_id=project_id,
                instrument_name=instrument_name,
                sample_unique_id=sample_unique_id,
                session_dsid=session_dsid,
            )
        except Exception as e:
            backend.logger.error(e)
            return jsonify({"error": str(e)}), 500
        try:
            flow_run = run_deployment(
                deployment_name,
                parameters={
                    "file": session_folder_path,
                    "instrument_name": instrument_name,
                    "project_id": project_id,
                    "orcid": orcid,
                    "sample_unique_id": sample_unique_id,
                    "session_dsid": dsid,
                    "kw_list": kw_list,
                    "comments": comments,
                },
                timeout=0,
            )
            return jsonify({
                "flow_run_id": str(flow_run.id),
                "project_id": project_id,
                "dsid": dsid,
            })
        except Exception as e:
            backend.logger.error(e)
            return jsonify({"error": str(e)}), 500

    # Non-session mode: each selected file becomes its own dataset.
    # - Single file (insitu or not): sync SHA lookup so the UI gets the dsid
    #   (existing or fresh mfid) immediately; always fire the flow.
    # - N>1 insitu: loop per file (insitu is rarely multi-file, no bulk path).
    # - N>1 non-insitu: one multi_file_upload run that builds the SHA map once
    #   and fans out internally; UI shows the project page.
    is_insitu = INSTRUMENT_FLOWS.get(instrument_name, "").startswith("insitu-upload")

    if len(session_folder_paths) == 1 or is_insitu:
        deployment_name = "insitu-upload/insitu-upload" if is_insitu else "upload-dataset/upload-dataset"
        try:
            results = []
            for path in session_folder_paths:
                dsid, _ = backend.resolve_dsid_for_file(path)
                flow_run = run_deployment(
                    deployment_name,
                    parameters={
                        "files": [path],
                        "dsid": dsid,
                        "instrument_name": instrument_name,
                        "project_id": project_id,
                        "orcid": orcid,
                        "sample_unique_id": sample_unique_id,
                        "kw_list": kw_list,
                        "comments": comments,
                    },
                    timeout=0,
                )
                results.append({"dsid": dsid, "flow_run_id": str(flow_run.id)})
        except Exception as e:
            backend.logger.error(e)
            return jsonify({"error": str(e)}), 500
        if len(results) == 1:
            return jsonify({
                "flow_run_id": results[0]["flow_run_id"],
                "project_id": project_id,
                "dsid": results[0]["dsid"],
            })
        return jsonify({"project_id": project_id, "uploads": results})

    # Generic multi-file path: fire one multi_file_upload run; it handles SHA
    # dedup and fans out per-file upload_dataset sub-flows.
    try:
        flow_run = run_deployment(
            "multi-file-upload/multi-file-upload",
            parameters={
                "files": session_folder_paths,
                "instrument_name": instrument_name,
                "project_id": project_id,
                "orcid": orcid,
                "sample_unique_id": sample_unique_id,
                "kw_list": kw_list,
                "comments": comments,
            },
            timeout=0,
        )
        return jsonify({
            "flow_run_id": str(flow_run.id),
            "project_id": project_id,
        })
    except Exception as e:
        backend.logger.error(e)
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
