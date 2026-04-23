"""
Crucible Upload UI — Flask backend
"""
import logging
import queue
import threading
import webbrowser
import tkinter as tk
import webbrowser
from tkinter import filedialog

from flask import Flask, Response, jsonify, render_template, request

import json

import backend
from instrument_conf import DEFAULT_BROWSE_DIR, IS_SESSION, DEFAULT_INSTRUMENT_NAME, PRINT_BARCODE_ENABLED, INSTRUMENTS

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

    def _sse(event, payload):
        return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

    def generate():
        try:
            # Step 1: Validate path depth
            from pathlib import Path
            MIN_DEPTH = 3
            parts = Path(session_folder_path).resolve().parts
            if len(parts) - 1 < MIN_DEPTH:
                yield _sse("error", {"error": f"Session folder is too close to the filesystem root. Please select a folder at least {MIN_DEPTH} levels deep."})
                return

            # Step 2: Copy to Google Drive
            yield _sse("progress", {"step": "gdrive", "message": "Copying files to Google Drive...", "percent": 5})
            try:
                backend.copy_all_files_to_gdrive(session_folder_path, instrument_name)
            except Exception as e:
                backend.logger.error(e)

            
            if IS_SESSION is False:
                session_id = None
                file_name = session_folder_path

                # Step 3: Upload the dataset
                yield _sse("progress", {"step": "file", "message": f"Processing file {file_name}"})
                try:
                    new_dsid = backend.upload_dataset(
                        session_folder_path, instrument_name, project_id, orcid,
                        session_name = None, session_dsid = None, sample_unique_id = sample_unique_id, 
                        kw_list = kw_list, comments = comments)
                    
                    yield _sse("complete", {"session_dsid": new_dsid, "project_id": project_id})

                except Exception as e:
                    yield _sse("error", {"error": f"Failed on {file_name}: {e}"})
                    return


            else:
                # Step 3: Identify session files
                yield _sse("progress", {"step": "identify", "message": "Identifying session files...", "percent": 15})
                session_files = backend.identify_session_files(session_folder_path)
                total_files = len(session_files)

                # Step 4: Create session dataset
                yield _sse("progress", {"step": "session", "message": "Creating session in Crucible...", "percent": 20})
                try:
                    session_name, session_id = backend.create_session(
                        session_folder_path, kw_list, comments,
                        orcid, project_id, instrument_name, sample_unique_id)
                    backend.logger.info(f"Created session '{session_name}' with ID {session_id}")
                except Exception as e:
                    backend.logger.error(e)
                    yield _sse("error", {"error": f"Failed to create session: {e}"})
                    return

                # Step 5: Process each file
                if total_files == 0:
                    yield _sse("progress", {"step": "done", "message": "No data files found, session created.", "percent": 100})
                else:
                    for i, file in enumerate(session_files):
                        file_name = Path(file).name
                        base_percent = 25
                        file_percent = base_percent + int((i + 1) / total_files * 75)
                        yield _sse("progress", {
                            "step": "file",
                            "message": f"Processing file {i + 1}/{total_files}: {file_name}",
                            "percent": min(file_percent, 99),
                            "current": i + 1,
                            "total": total_files,
                        })
                        try:
                            new_dsid = backend.upload_dataset(
                                file, instrument_name, project_id, orcid,
                                session_name, session_id, sample_unique_id,
                                kw_list, comments)
                            backend.logger.info(f"Uploaded file '{file_name}' as dataset ID {new_dsid}")
                        except Exception as e:
                            backend.logger.error(e)
                            yield _sse("error", {"error": f"Failed on {file_name}: {e}"})
                            return

                yield _sse("complete", {"session_dsid": session_id, "project_id": project_id})

        except Exception as e:
            backend.logger.error(e)
            yield _sse("error", {"error": str(e)})

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    # Flask runs in a daemon thread; tkinter mainloop holds the main thread.
    flask_thread = threading.Thread(
        target=lambda: app.run(debug=False, port=5000), daemon=True
    )
    flask_thread.start()
    webbrowser.open("http://localhost:5000")
    _tk_root.after(50, _check_browse_queue)
    _tk_root.mainloop()
