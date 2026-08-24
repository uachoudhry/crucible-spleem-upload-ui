"""
Registers Prefect flows as deployments and serves them.

Usage:
    export PREFECT_API_URL=http://127.0.0.1:4200/api
    python serve_flows.py
"""
import os
os.environ['PREFECT_API_DATABASE_TIMEOUT'] = '30.0'

from prefect import serve
from prefect_backend import (run_shell, multi_file_upload, session_upload, upload_dataset,
                             ensure_upload_concurrency_limit)

if __name__ == "__main__":
    # Large (>=1 GiB) transfers are throttled separately by a global concurrency
    # limit; serve's limit below still governs small-file parallelism.
    ensure_upload_concurrency_limit()
    # run_shell(f'rclone config show')
    multi_deploy = multi_file_upload.to_deployment(name="multi-file-upload")
    session_deploy = session_upload.to_deployment(name="session-upload")
    upload_deploy = upload_dataset.to_deployment(name="upload-dataset")
    serve(multi_deploy, session_deploy, upload_deploy, limit=10)
