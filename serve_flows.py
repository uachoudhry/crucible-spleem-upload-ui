"""
Registers Prefect flows as deployments and serves them.

Usage:
    export PREFECT_API_URL=http://127.0.0.1:4200/api
    python serve_flows.py
"""
import os
os.environ['PREFECT_API_DATABASE_TIMEOUT'] = '30.0'

from prefect import serve
from prefect_backend import run_shell, insitu_upload, multi_file_upload, tem_session_upload, upload_dataset

if __name__ == "__main__":
    run_shell(f'rclone config show')
    insitu_deploy = insitu_upload.to_deployment(name="insitu-upload")
    multi_deploy = multi_file_upload.to_deployment(name="multi-file-upload")
    tem_deploy = tem_session_upload.to_deployment(name="tem-session-upload")
    upload_deploy = upload_dataset.to_deployment(name="upload-dataset")
    serve(insitu_deploy, multi_deploy, tem_deploy, upload_deploy, limit=10)
