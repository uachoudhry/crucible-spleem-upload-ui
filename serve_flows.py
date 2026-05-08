"""
Registers Prefect flows as deployments and serves them.

Usage:
    export PREFECT_API_URL=http://127.0.0.1:4200/api
    python serve_flows.py
"""
import os
os.environ['PREFECT_API_DATABASE_TIMEOUT'] = '30.0'

from prefect import serve
from prefect_backend import (run_shell, insitu_upload, tem_session_upload, upload_child_dataset,
                             spleem_session_upload, spleem_upload_child_dataset, _rclone_available)

if __name__ == "__main__":
    if _rclone_available():
        run_shell('rclone config show')
    else:
        import logging
        logging.getLogger(__name__).warning("rclone not found — cloud copy will be skipped, direct upload will be used")
    insitu_deploy = insitu_upload.to_deployment(name="insitu-upload")
    tem_deploy = tem_session_upload.to_deployment(name="tem-session-upload")
    child_deploy = upload_child_dataset.to_deployment(name="upload-child-dataset")
    spleem_deploy = spleem_session_upload.to_deployment(name="spleem-session-upload")
    spleem_child_deploy = spleem_upload_child_dataset.to_deployment(name="spleem-upload-child-dataset")
    serve(insitu_deploy, tem_deploy, child_deploy, spleem_deploy, spleem_child_deploy, limit=10)
