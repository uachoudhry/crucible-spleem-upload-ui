"""
Backend functions for the Crucible upload UI.
Replace these stubs with your real implementations.
"""
import re
from pathlib import Path
import subprocess as sp
from crucible import CrucibleClient
from crucible.models import BaseDataset
import logging
from prefect import flow, task
from prefect.logging import get_run_logger

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


class MultipleSessionsFound(Exception):
    def __init__(self, sessions: list[dict]):
        self.sessions = sessions
        super().__init__(f"Multiple sessions found: {len(sessions)}")


try:
    client = CrucibleClient()
    assert client.api_key is not None
    logger.info(f'Connected to Crucible Client with API url: {client.api_url}')

except Exception as e:
    logger.error(f'Client connection failed with error {e}. \
                 You can check your Crucible configuration by \
                 running `crucible config show` in the command line')


def run_shell(cmd: str, checkflag: bool = True, background: bool = False) -> sp.CompletedProcess | sp.Popen:
    if background:
        return sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.STDOUT, shell=True, universal_newlines=True)
    return sp.run(cmd, stdout=sp.PIPE, stderr=sp.STDOUT, shell=True, universal_newlines=True, check=checkflag)


def run_rclone_command(source_path: str = "", destination_path: str = "", cmd: str = "copy",
                       background: bool = False, checkflag: bool = True, dry_run = False) -> sp.CompletedProcess | sp.Popen:
    if len(destination_path.strip()) > 0:
        destination_path = f'"{destination_path}"'
    
    source_path, destination_path = (x.replace(":gcs", "") for x in (source_path, destination_path))
    
    rclone_cmd = f'rclone {cmd} "{source_path}" {destination_path}'

    # Dry run first — check both exit code and output for errors
    if dry_run:
        dry_run = run_shell(f'{rclone_cmd} --dry-run', background=False, checkflag=False)
        if dry_run.returncode != 0 or "ERROR" in (dry_run.stdout or "").upper():
            msg = (
                f"rclone dry run failed. Please check your rclone configuration "
                f"with `rclone config`.\n{dry_run.stdout or ''}"
            )
            logger.error(msg)
            raise RuntimeError(msg)

    # Real copy
    logger.info(f'copying file {source_path=} to {destination_path=}')
    return run_shell(rclone_cmd, background=background, checkflag=checkflag)


def lookup_user_by_email(email: str) -> dict:
    """
    Look up a user by email address.

    Returns a dict with keys:
        name    (str) display name
        orcid   (str) ORCID identifier
        projects (list[str]) list of project ids representing projects the user belongs to

    Returns an empty dict if the user is not found.
    """
    user_info = client.users.get(email=email)
    logger.info(f"Lookup for email '{email}' returned: {user_info}")
    if user_info is None:
        return {}

    user_name = f"{user_info['first_name']} {user_info['last_name']}"
    logger.info(f"User name for email '{email}' is: {user_name}")
    projects = client.projects.list(user_info['unique_id'])
    project_ids = [x['project_id'] for x in projects]
    project_ids.sort()
    logger.info(f"Projects for email '{email}' are: {project_ids}")
    return {'name': user_name,
            'orcid': user_info['unique_id'],
            'projects': project_ids}


def lookup_sample(sample_name: str | None = None, sample_unique_id: str | None = None, project_id: str | None = None) -> dict:
    """
    Look up a sample by its name or sample_unique_id.

    Returns a dict with keys:
            unique_id: string
            sample_name: string
            sample_type: string
            date_created: string
            description: string

    Returns an empty dict if not found.
    """
    kwargs = {k: v for k, v in {
        "sample_name": sample_name,
        "unique_id": sample_unique_id,   # client.list_samples expects "unique_id"
        "project_id": project_id,
    }.items() if v is not None}

    found_samples = client.samples.list(**kwargs)

    # If you only find one sample - great, otherwise warn user
    if len(found_samples) == 1:
        sample = found_samples[0]
        
        parts = [f"Type: {sample.get('sample_type', '')}" ,                                                                                       
                 f"Created: {sample.get('date_created', '')}",                                                                                  
                 sample.get("description", "")
                 ]
        
        return_fields = ['unique_id', 'sample_name']
        formatted_sample = {k: sample[k] for k in return_fields}                                                                                                                                            
        formatted_sample['description'] = "\n".join(p for p in parts if p)      
        return formatted_sample

    elif len(found_samples) > 1:
        logger.warning(f'Multiple samples found - {found_samples=}')
        return {}

    else:
        logger.warning(f'No sample found with {sample_name=} in project {project_id}. Note: sample names are case sensitive.')
        return {}


def create_sample(sample_name: str, owner_orcid: str, project_id: str,
                   unique_id: str | None = None, description: str | None = None,
                   timestamp: str | None = None, sample_type: str | None = None) -> dict:
    kwargs = {k: v for k, v in {
        "unique_id": unique_id,
        "sample_name": sample_name,
        "description": description,
        "timestamp": timestamp,
        "project_id": project_id,
        "sample_type": sample_type,
        "owner_user_id": owner_orcid,
    }.items() if v is not None}

    result = client.samples.create(**kwargs)
    logger.info(f"Created sample: {result}")
    #created = result.get('created_record', result)
    created = result
    return {
        'unique_id': created.get('unique_id', ''),
        'sample_name': created.get('sample_name', sample_name),
    }


def print_sample_barcode(sample_unique_id, sample_name):
    from image_print import make_qr, make_nirvana_image, print_label
    # qr code
    qr_img = make_qr(sample_unique_id)

    # label image
    make_nirvana_image(qr_img, [sample_name, sample_unique_id[0:13]], "batch.png")
    print_label("Brother PT-D610BT", "batch.png")
    return


def get_emi_file_name(serfile: str) -> str:
    no_ext = serfile.split(".ser")[0]
    no_rep = re.sub('_[0-9]*$', '', no_ext)
    return f"{no_rep}.emi"

def check_session_depth(session_folder_path: str, min_depth: int = 3) -> None:
    parts = Path(session_folder_path).resolve().parts
    if len(parts) - 1 <min_depth:  # subtract 1 to not count the root
        raise ValueError(f"Session folder is too close to the filesystem root. Please select a folder at least {min_depth} levels deep.")
    else:
        return


def check_existing_sessions(session_folder_path: str, orcid: str, project_id: str,
                            instrument_name: str) -> list[dict]:
    project_id = project_id.replace('Internal Research (', '').replace(')', '').strip()
    session_name = Path(session_folder_path).name
    dsname = f'{instrument_name} session: {session_name}'
    existing = client.datasets.list(owner_orcid=orcid, project_id=project_id, dataset_name=dsname)
    return [
        {
            'unique_id': ds.get('unique_id', ''),
            'dataset_name': ds.get('dataset_name', ''),
            'creation_time': ds.get('creation_time', ''),
            'modification_time': ds.get('modification_time', ''),
        }
        for ds in existing
    ]


def create_session(session_folder_path: str, kw_list: list[str], comments: str, orcid: str,
                   project_id: str, instrument_name: str, sample_unique_id: str | None = None,
                   session_dsid: str | None = None) -> tuple[str, str]:
    project_id = project_id.replace('Internal Research (', '').replace(')', '').strip()
    session_name = Path(session_folder_path).name
    dsname = f'{instrument_name} session: {session_name}'

    if session_dsid is not None and session_dsid != "new":
        use_session_dsid = session_dsid
    else:
        session_ds = BaseDataset(dataset_name=dsname,
                                owner_orcid=orcid,
                                project_id=project_id,
                                instrument_name=instrument_name,
                                measurement=f'full {instrument_name} session',
                                session_name=session_name)

        new_sess_ds = client.datasets.create(session_ds,
                                            scientific_metadata={'comments': comments},
                                            keywords=kw_list)

        use_session_dsid = new_sess_ds['created_record']['unique_id']

    if sample_unique_id is not None:
        client.samples.add_to_dataset(sample_id=sample_unique_id,
                                      dataset_id=use_session_dsid)
    return session_name, use_session_dsid


def get_or_create_insitu_dataset(file_path: str, orcid: str, project_id: str,
                                 kw_list: list[str], comments: str) -> str:
    """Return the dsid of an existing insitu dataset for this file/user/project,
    creating an empty one if none exists. Used by /api/upload to obtain a dsid
    synchronously so the UI can show the Crucible link before the flow runs.
    """
    project_id = project_id.replace('Internal Research (', '').replace(')', '').strip()
    dataset_name = Path(file_path).name

    existing = client.datasets.list(
        dataset_name=dataset_name,
        owner_orcid=orcid,
        project_id=project_id,
        limit=None,
    )
    found_dsid = None
    if existing:
        existing.sort(key=lambda d: d.get('modification_time') or '', reverse=True)
        found_dsid = existing[0]['unique_id']

    ds_kwargs = {k: v for k, v in dict(
        unique_id=found_dsid,
        dataset_name=dataset_name,
        owner_orcid=orcid,
        project_id=project_id,
    ).items() if v is not None}
    ds = BaseDataset(**ds_kwargs)
    scimd = {'comments': comments} if comments else {}
    new_ds = client.datasets.create(ds, scientific_metadata=scimd, keywords=kw_list)
    return new_ds['created_record']['unique_id']


@task
def identify_session_files(session_folder_path: str) -> list[str]:
    from instrument_conf import ACCEPTABLE_FILE_TYPES
    max_size = 20 * 1024 ** 3  # 20 GiB
    return [
        str(f) for f in Path(session_folder_path).rglob("*") if f.is_file()
        and f.suffix.lower() in ACCEPTABLE_FILE_TYPES
        and f.stat().st_size < max_size
    ]


@task(retries=3, retry_delay_seconds=10)
def copy_all_files_to_gdrive(session_folder_path: str, instrument_name: str) -> None:
    logger = get_run_logger()
    p = Path(session_folder_path)
    relative_folder_path = p.relative_to(p.anchor).as_posix()
    dest = f"{instrument_name}-gdrive:/crucible-uploads/{instrument_name}/{relative_folder_path}"
    logger.info(f'Copying {session_folder_path} to {dest}')
    
    try:
        run_rclone_command(session_folder_path, dest, 'copy', background=True)
    except Exception as e:
        logger.error(f'rclone copy for {session_folder_path} to google drive failed with error {e}')


def _compute_sha256(file_path: str) -> str:
    import hashlib
    _CHUNK = 32 * 1024 * 1024
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for block in iter(lambda: f.read(_CHUNK), b''):
            h.update(block)
    return h.hexdigest()


@task
def create_dataset(files: list[str],
                   instrument_name: str | None = None,
                   project_id: str | None = None,
                   orcid: str | None = None,
                   session_name: str | None = None,
                   kw_list: list[str] = [],
                   comments: str | None = None) -> str:
    logger = get_run_logger()

    # Dedup + retry resume: for each file, check if an associated file with the
    # same SHA256 already exists in a dataset for this session. If found, pass
    # that unique_id to BaseDataset so datasets.create() runs against the existing
    # record — the file upload is skipped (SHA256 dedup in _upload_file_gcs) and
    # any previously failed steps (metadata, keywords, links) are retried.
    found_dsid = None
    for file_path in files:
        file_sha256 = _compute_sha256(file_path)
        logger.info(f"SHA256 for {Path(file_path).name}: {file_sha256}")
        for file_rec in client.files.list_files(sha256_hash=file_sha256):
            dsid = file_rec.get('dataset_mfid')
            if not dsid:
                continue
            ds = client.datasets.get(dsid)
            if (ds
                    and ds.get('session_name') == session_name
                    and ds.get('project_id') == project_id
                    and ds.get('owner_orcid') == orcid):
                found_dsid = dsid
                logger.info(f"File {Path(file_path).name} already in dataset {found_dsid}; resuming")
                break
        if found_dsid:
            break

    ds_kwargs = {k: v for k, v in dict(
        unique_id=found_dsid,
        owner_orcid=orcid,
        project_id=project_id,
        instrument_name=instrument_name,
        session_name=session_name,
    ).items() if v is not None}
    ds = BaseDataset(**ds_kwargs)
    scimd = {'comments': comments} if comments else {}
    new_ds = client.datasets.create(
        ds,
        scientific_metadata=scimd,
        keywords=kw_list,
        files_to_upload=files,
        wait_for_ingestion_response=True,
    )
    new_ds_dsid = new_ds['created_record']['unique_id']
    logger.info(f"{'Resumed' if found_dsid else 'Created'} dataset {new_ds_dsid} for {', '.join(Path(f).name for f in files)}")
    return new_ds_dsid


@task(retries=3, retry_delay_seconds=5)
def link_dataset_to_session(new_ds_dsid: str, session_dsid: str | None = None):
    if session_dsid is not None:
        response = client.datasets.link_parent_child(parent_dataset_id=session_dsid, child_dataset_id=new_ds_dsid)
        return response
    return None


@task(retries=3, retry_delay_seconds=5)
def link_dataset_and_sample(new_ds_dsid: str, sample_unique_id: str | None = None):
    if sample_unique_id is not None:
        response = client.samples.add_to_dataset(dataset_id = new_ds_dsid, sample_id = sample_unique_id)
        return response
    return None

@task(retries=3, retry_delay_seconds=5)
def request_insitu_aggregation(new_ds_dsid: str):
    response = client.datasets.request_insitu_aggregation(new_ds_dsid)
    return response


def _run_name(prefix):
    def generate():
        from prefect.runtime import flow_run
        fileinput = flow_run.parameters.get('file', None)
        if fileinput is None:
            fileinput = flow_run.parameters.get('files', [None])[0]
        return f"{prefix}-{Path(fileinput).name}"
    return generate


@task(retries=3, retry_delay_seconds=10)
def add_file_to_insitu_dataset(dsid: str, file_path: str) -> None:
    client.datasets.add_file_to_dataset(
        dsid=dsid, file_path=file_path, wait_for_ingestion_response=True,
    )


# flow to upload an insitu dataset (dataset record pre-created by /api/upload)
@flow(flow_run_name=_run_name("insitu-upload"))
def insitu_upload(file: str,
                  instrument_name: str,
                  project_id: str,
                  orcid: str,
                  sample_unique_id: str | None = None,
                  session_dsid: str | None = None,
                  kw_list: list[str] = [],
                  comments: str | None = None) -> str:

    add_file_to_insitu_dataset(session_dsid, file)
    request_insitu_aggregation(session_dsid)
    return session_dsid

# sub flow to upload a dataset as the child of a session
@flow(flow_run_name=_run_name("upload"))
def upload_child_dataset(files: list,
                         instrument_name: str,
                         project_id: str,
                         orcid: str,
                         session_name: str,
                         session_dsid: str,
                         sample_unique_id: str | None = None,
                         kw_list: list[str] = [],
                         comments: str | None = None) -> str:
    
    new_ds_dsid = create_dataset(files = files,
                                 instrument_name = instrument_name,
                                 project_id=project_id,
                                 orcid=orcid,
                                 session_name=session_name,
                                 kw_list=kw_list,
                                 comments=comments)

    link_dataset_to_session(new_ds_dsid, session_dsid)
    link_dataset_and_sample(new_ds_dsid, sample_unique_id)
    return new_ds_dsid

# flow to upload a session of TEM data
@flow(flow_run_name=_run_name("tem-session"))
def tem_session_upload(file: str, instrument_name: str, project_id: str, orcid: str,
                       sample_unique_id: str | None = None, session_dsid: str | None = None,
                       kw_list: list[str] = [], comments: str | None = None) -> str:
    import time
    import os
    import requests as req
    from prefect.deployments import run_deployment
    logger = get_run_logger()

    session_folder_path = file

    check_session_depth(session_folder_path)

    # copy_all_files_to_gdrive(session_folder_path, instrument_name)  # not used for SPLEEM

    session_name, session_dsid = create_session(
        session_folder_path, kw_list, comments or "",
        orcid, project_id, instrument_name, sample_unique_id,
        session_dsid=session_dsid)

    # returns list of files in folder path that are less than 20GB 
    # with an accepted file type
    session_files = identify_session_files(session_folder_path)
    logger.info(f'{session_files=}')
    # Submit all child flows in parallel (timeout=0 returns immediately)
    child_runs = []
    for f in session_files:
        time.sleep(0.3)
        dsfiles = [f]
        # if f.endswith('ser'):
        #     dsfiles.append(get_emi_file_name(f))

        run = run_deployment(
            "upload-child-dataset/upload-child-dataset",
            parameters={
                "files": dsfiles,
                "instrument_name": instrument_name,
                "project_id": project_id,
                "orcid": orcid,
                "session_name": session_name,
                "session_dsid": session_dsid,
                "sample_unique_id": sample_unique_id,
                "kw_list": kw_list,
                "comments": comments,
            },
            timeout=0,
        )
        child_runs.append(run)
        logger.info(f"Submitted child flow for {Path(f).name}: {run.id}")

    # Wait for all children to reach a terminal state
    terminal_states = {"COMPLETED", "FAILED", "CRASHED", "CANCELLED"}
    pending = {str(r.id) for r in child_runs}
    failed = []

    while pending:
        time.sleep(5)
        still_pending = set()
        for rid in pending:
            api_url = os.environ.get("PREFECT_API_URL", "http://127.0.0.1:4200/api")
            try:
                resp = req.get(f"{api_url}/flow_runs/{rid}", timeout=10)
                resp.raise_for_status()
                state = resp.json().get("state", {}).get("type", "")
            except Exception as e:
                logger.warning(f"Could not poll flow run {rid}: {e}; will retry")
                still_pending.add(rid)
                continue
            if state not in terminal_states:
                still_pending.add(rid)
            elif state != "COMPLETED":
                failed.append(rid)
                logger.error(f"Child flow run {rid} ended with state {state}")
        pending = still_pending

    if failed:
        logger.error(f"{len(failed)} child flow(s) failed. Retry them from the Prefect UI.")

    return session_dsid

