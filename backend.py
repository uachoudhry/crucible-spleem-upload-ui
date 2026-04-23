"""
Backend functions for the Crucible SPLEEM upload UI.
Adapted from crucible-tem-upload-ui for the SPLEEM microscope.
"""
from pathlib import Path
import subprocess as sp
from crucible import CrucibleClient
from crucible.models import BaseDataset
import logging

logger = logging.getLogger(__name__)


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
    # TODO: internal research formatting
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


def _rclone_available() -> bool:
    """Return True if rclone is installed and reachable."""
    result = sp.run("rclone version", shell=True, stdout=sp.PIPE, stderr=sp.STDOUT)
    return result.returncode == 0


def create_session(session_folder_path: str, kw_list: list[str], comments: str, orcid: str,
                   project_id: str, instrument_name: str, sample_unique_id: str | None = None) -> tuple[str, str]:
    project_id = project_id.replace('Internal Research (', '').replace(')', '').strip()
    session_name = Path(session_folder_path).name
    session_ds = BaseDataset(dataset_name=f'{instrument_name} session: {session_name}',
                             owner_orcid=orcid,
                             project_id=project_id,
                             instrument_name=instrument_name,
                             measurement=f'full {instrument_name} session',
                             session_name=session_name)

    new_sess_ds = client.datasets.create(session_ds,
                                         scientific_metadata={'comments': comments},
                                         keywords=kw_list)

    sess_dsid = new_sess_ds['created_record']['unique_id']
    if sample_unique_id is not None:
        client.samples.add_to_dataset(sample_id=sample_unique_id,
                                      dataset_id=sess_dsid)
    return session_name, sess_dsid


def identify_session_files(session_folder_path: str) -> list[str]:
    # TODO: use Path.rglob for recursive discovery
    acceptable_suffixes = {'.h5', '.tif', '.tiff', '.png', '.jpg', '.jpeg', '.csv', '.txt'}
    max_size = 20 * 1024 ** 3  # 20 GiB
    return [
        str(f) for f in Path(session_folder_path).iterdir()
        if f.is_file()
        and f.suffix.lower() in acceptable_suffixes
        and f.stat().st_size < max_size
    ]


def copy_all_files_to_gdrive(session_folder_path: str, instrument_name: str) -> None:
    if not _rclone_available():
        logger.warning('rclone not found — skipping Google Drive backup. '
                       'Install and configure rclone to enable cloud backup.')
        return
    p = Path(session_folder_path)
    relative_folder_path = p.relative_to(p.anchor).as_posix()
    dest = f"{instrument_name}-gdrive:/crucible-uploads/{instrument_name}/{relative_folder_path}"
    logger.info(f'Copying {session_folder_path} to {dest}')
    try:
        run_rclone_command(session_folder_path, dest, 'copy', background=True)
    except Exception as e:
        logger.error(f'rclone copy for {session_folder_path} to google drive failed with error {e}')


def copy_dataset_to_cloud(file: str, instrument_name: str, storage_bucket: str = 'crucible-uploads',
                          rclone_mount: str = 'mf-cloud-storage') -> list[str]:
    if not _rclone_available():
        logger.warning('rclone not found — skipping cloud storage copy. '
                       'Install and configure rclone to enable cloud backup.')
        return []
    p = Path(file)
    lp = p
    local_rel_path = lp.parent.relative_to(lp.parent.anchor).as_posix()
    cloud_rel_path = f"{instrument_name}/{local_rel_path}"
    rclone_dest = f'{rclone_mount}:{storage_bucket}/{cloud_rel_path}'
    run_rclone_command(file, rclone_dest, 'copy', background=True, checkflag=True, dry_run=True)
    return [f'{cloud_rel_path}/{lp.name}']


def upload_dataset(file: str, instrument_name: str, project_id: str, orcid: str,
                      session_name: str=None, session_dsid: str = None, sample_unique_id: str=None,
                      kw_list: list[str] = [], comments: str = None) -> str:
    # copy the files to temp bucket (skipped gracefully if rclone not configured)
    cloud_files = copy_dataset_to_cloud(file, instrument_name)

    # create the dataset
    ds = BaseDataset(file_to_upload=cloud_files[0] if cloud_files else Path(file).name,
                     owner_orcid=orcid,
                     project_id=project_id,
                     instrument_name=instrument_name,
                     session_name=session_name)

    scimd = {'comments': comments}  # TODO: ADD CLAUDE API CALL
    new_ds = client.datasets.create(ds, scientific_metadata=scimd, keywords=kw_list)

    new_ds_dsid = new_ds['created_record']['unique_id']
    client.datasets.request_ingestion(new_ds_dsid, ingestion_class=None)

    if session_dsid is not None:
        client.datasets.link_parent_child(parent_dataset_id=session_dsid, child_dataset_id=new_ds_dsid)
    if sample_unique_id is not None:
        client.samples.add_to_dataset(dataset_id = new_ds_dsid, sample_id = sample_unique_id)

    return new_ds_dsid


# def upload_session(
#     orcid: str,
#     project_id: str,
#     instrument_name: str,
#     sample_unique_id: str,
#     session_folder_path: str,
#     kw_list: list[str] = [],
#     comments: str = '',
# ) -> bool:
#     """
#     Run the upload with the collected form data.

#     Returns True on success, False on failure.
#     """
#     # Guard against uploading from high-level directories (e.g. "/" or "D:\")
#     MIN_DEPTH = 3  # require at least 3 levels below root
#     parts = Path(session_folder_path).resolve().parts
#     if len(parts) - 1 < MIN_DEPTH:
#         raise ValueError(
#             f"Session folder '{session_folder_path}' is too close to the filesystem root. "
#             f"Please select a more specific folder (at least {MIN_DEPTH} levels deep)."
#         )

#     # Copy the files to google drive
#     try:
#         copy_all_files_to_gdrive(session_folder_path, instrument_name)
#     except Exception as e:
#         logger.error(e)

#     # Identify session_files for Crucible
#     session_files = identify_session_files(session_folder_path)

#     # Create a session dataset in Crucible
#     try:
#         session_name, session_id = create_session(session_folder_path,
#                                                    kw_list,
#                                                    comments,
#                                                    orcid,
#                                                    project_id,
#                                                    instrument_name,
#                                                    sample_unique_id)
#     except Exception as e:
#         logger.error(e)
#         return
    
#     # process each file as dataset
#     for file in session_files:
#         try:
#             process_each_file(file, instrument_name, project_id, orcid,
#                               session_name, session_id, sample_unique_id, kw_list, comments)
#         except Exception as e:
#             msg = f'Crucible upload failed for {file} with error {e}'
#             logger.error(msg)
#             raise Exception(msg)

#     return session_id
