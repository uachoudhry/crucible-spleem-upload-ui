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
import asyncio
from prefect import flow, task
from prefect.cache_policies import INPUTS

logger = logging.getLogger(__name__)


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
    user_info = client.get_user(email=email)
    logger.info(f"Lookup for email '{email}' returned: {user_info}")
    if user_info is None:
        # TODO: prompt user to search by orcid
        return {}

    user_name = f"{user_info['first_name']} {user_info['last_name']}"
    logger.info(f"User name for email '{email}' is: {user_name}")
    projects = client.list_projects(user_info['orcid'])
    project_ids = [x['project_id'] for x in projects]
    project_ids.sort()
    logger.info(f"Projects for email '{email}' are: {project_ids}")
    return {'name': user_name,
            'orcid': user_info['orcid'],
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

    found_samples = client.list_samples(**kwargs)

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
        "owner_orcid": owner_orcid,
    }.items() if v is not None}

    result = client.samples.create(**kwargs)
    logger.info(f"Created sample: {result}")
    created = result.get('created_record', result)
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


@task(retries=3, retry_delay_seconds=5)
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

@task
def identify_session_files(session_folder_path: str) -> list[str]:
    acceptable_suffixes = {'.emd', '.dm3', '.dm4', '.bcf', '.ser', '.mcr', '.h5'}
    max_size = 2 * 1024 ** 3  # 2 GiB
    return [
        str(f) for f in Path(session_folder_path).rglob("*") if f.is_file()
        and f.suffix.lower() in acceptable_suffixes
        and f.stat().st_size < max_size
    ]


@task(retries=3, retry_delay_seconds=10)
def copy_all_files_to_gdrive(session_folder_path: str, instrument_name: str) -> None:
    p = Path(session_folder_path)
    relative_folder_path = p.relative_to(p.anchor).as_posix()
    dest = f"{instrument_name}-gdrive:/crucible-uploads/{instrument_name}/{relative_folder_path}"
    logger.info(f'Copying {session_folder_path} to {dest}')
    
    try:
        run_rclone_command(session_folder_path, dest, 'copy', background=True)
    except Exception as e:
        logger.error(f'rclone copy for {session_folder_path} to google drive failed with error {e}')


@task(retries=3, retry_delay_seconds=10)
def copy_dataset_to_cloud(file: str, instrument_name: str, storage_bucket: str = 'crucible-uploads',
                          rclone_mount: str = 'mf-cloud-storage') -> list[str]:
    p = Path(file)
    ftype = p.suffix.lstrip('.')

    # find any associated files
    files_to_upload = [file, get_emi_file_name(file)] if ftype == 'ser' else [file]

    # copy
    cloud_files = []
    for i, local_file_path in enumerate(files_to_upload):
        lp = Path(local_file_path)
        local_rel_path = lp.parent.relative_to(lp.parent.anchor).as_posix()
        cloud_rel_path = f"{instrument_name}/{local_rel_path}"
        rclone_dest = f'{rclone_mount}:{storage_bucket}/{cloud_rel_path}'
        dry_run = True if i == 0 else False  # only do dry run for the first file to check for errors before copying all files
        run_rclone_command(local_file_path, rclone_dest, 'copy', background=False, checkflag=True, dry_run = dry_run)
        
        cloud_files.append(f'{cloud_rel_path}/{lp.name}')

    return cloud_files


@task(retries=3, retry_delay_seconds=5)
def create_sql_record_for_dataset(cloud_files: list[str], 
                                  instrument_name: str | None = None,
                                  project_id: str | None = None,
                                  orcid: str | None = None,
                                  session_name: str | None = None,
                                  kw_list: list[str] = [],
                                  comments: str | None = None):
    
    existing = client.datasets.list(file_to_upload = cloud_files[0], owner_orcid = orcid, project_id = project_id, session_name = session_name)
    if len(existing) > 0:
        existing.sort(key=lambda ds: ds.get('modification_time', ''), reverse=True)
        return existing[0]['unique_id']
    
    # create the dataset
    ds_kwargs = {k: v for k, v in dict(
        file_to_upload=cloud_files[0],
        owner_orcid=orcid,
        project_id=project_id,
        instrument_name=instrument_name,
        session_name=session_name,
    ).items() if v is not None}
    ds = BaseDataset(**ds_kwargs)

    scimd = {'comments': comments}  # TODO: ADD CLAUDE API CALL
    new_ds = client.datasets.create(ds, scientific_metadata=scimd, keywords=kw_list)

    new_ds_dsid = new_ds['created_record']['unique_id']
    return new_ds_dsid


@task(retries=3, retry_delay_seconds=5)
def run_data_ingestion(new_ds_dsid, ingestion_class: str | None = None):
    ingestion_status = client.datasets.request_ingestion(new_ds_dsid, ingestion_class=ingestion_class, wait_for_response=True)
    if ingestion_status['status'] != 'complete':
        logger.error(f'Ingestion failed for dataset {new_ds_dsid} with status {ingestion_status}')
        raise RuntimeError(f'Ingestion failed for dataset {new_ds_dsid} with status {ingestion_status}')
    
    return ingestion_status['status']


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
def request_insitu_aggregation(new_ds_dsid: str, ingestion_status: str):
    response = client.datasets.request_insitu_aggregation(new_ds_dsid)
    return response


RESULTS_DIR = Path(".flow_results")
RESULTS_DIR.mkdir(exist_ok=True)


def _save_flow_result(dsid: str):
    from prefect.runtime import flow_run
    (RESULTS_DIR / str(flow_run.id)).write_text(dsid)


def _run_name(prefix):
    def generate():
        from prefect.runtime import flow_run
        return f"{prefix}-{Path(flow_run.parameters['file']).name}"
    return generate


@flow(flow_run_name=_run_name("insitu-upload"), persist_result=True)
def insitu_upload(file: str, instrument_name: str, project_id: str, orcid: str, sample_unique_id: str | None = None, session_dsid: str | None = None, kw_list: list[str] = [], comments: str | None = None) -> str:
    # copy the files to temp bucket
    cloud_files = copy_dataset_to_cloud(file, instrument_name)

    # create the dataset
    new_ds_dsid = create_sql_record_for_dataset(cloud_files, None, project_id, orcid, kw_list=kw_list, comments=comments)

    # request ingestion
    ingestion_status = run_data_ingestion(new_ds_dsid, ingestion_class=None)

    # check about linking to session and sample
    # session_link_status = link_dataset_to_session(new_ds_dsid, session_dsid)
    # sample_link_status = link_dataset_and_sample(new_ds_dsid, sample_unique_id)

    # request post processing
    aggregation_status = request_insitu_aggregation(new_ds_dsid, ingestion_status)
    _save_flow_result(new_ds_dsid)
    return new_ds_dsid


@flow(flow_run_name=_run_name("upload"))
def upload_child_dataset(file: str, instrument_name: str, project_id: str, orcid: str,
                         session_name: str, session_dsid: str,
                         sample_unique_id: str | None = None,
                         kw_list: list[str] = [], comments: str | None = None) -> str:
    cloud_files = copy_dataset_to_cloud(file, instrument_name)
    new_ds_dsid = create_sql_record_for_dataset(cloud_files, instrument_name, project_id, orcid,
                                 session_name=session_name, kw_list=kw_list, comments=comments)
    run_data_ingestion(new_ds_dsid)
    link_dataset_to_session(new_ds_dsid, session_dsid)
    link_dataset_and_sample(new_ds_dsid, sample_unique_id)
    return new_ds_dsid


@flow(flow_run_name=_run_name("tem-session"), persist_result=True)
def tem_session_upload(file: str, instrument_name: str, project_id: str, orcid: str,
                       sample_unique_id: str | None = None, session_dsid: str | None = None,
                       kw_list: list[str] = [], comments: str | None = None) -> str:
    import time
    from prefect.deployments import run_deployment

    session_folder_path = file

    check_session_depth(session_folder_path)

    copy_all_files_to_gdrive(session_folder_path, instrument_name)

    session_name, session_dsid = create_session(
        session_folder_path, kw_list, comments or "",
        orcid, project_id, instrument_name, sample_unique_id,
        session_dsid=session_dsid)

    session_files = identify_session_files(session_folder_path)

    # Submit all child flows in parallel (timeout=0 returns immediately)
    child_runs = []
    for f in session_files:
        time.sleep(0.3)
        run = run_deployment(
            "upload-child-dataset/upload-child-dataset",
            parameters={
                "file": f,
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
            import requests as req
            import os
            api_url = os.environ.get("PREFECT_API_URL", "http://127.0.0.1:4200/api")
            resp = req.get(f"{api_url}/flow_runs/{rid}")
            state = resp.json().get("state", {}).get("type", "")
            if state not in terminal_states:
                still_pending.add(rid)
            elif state != "COMPLETED":
                failed.append(rid)
                logger.error(f"Child flow run {rid} ended with state {state}")
        pending = still_pending

    if failed:
        logger.error(f"{len(failed)} child flow(s) failed. Retry them from the Prefect UI.")

    _save_flow_result(session_dsid)
    return session_dsid

