# crucible-spleem-upload-ui

This is a flask based application for uploading SPLEEM generated data files to the [Crucible data platform](https://crucible.lbl.gov). The app is meant to run locally on instrument support PCs.<br> The following workflow is supported by this application: 

- **Users can enter their ORCID or email address:**<br>
This will populate a list of projects for which the user has access. It will also ensure that the data uploaded is associated with that user account.

- **Select a project to upload the dataset to**<br>
All members of the project will then have access to the uploaded data through the Crucible platform

- **Select the instrument from which they are uploading data**

- **Search for a sample by sample_name or unique_id**
This will display the sample details and create a relationship between any uploaded datasets and the sample provided.

- **Select a folder from their local file system to upload**
The name of this folder will be used to create a dataset object in the Crucible platform with a measurement type of the format `{instrument_name} full session`.  From this folder, all supported files* will be uploaded as datasets to the platform and linked as "children" of the session dataset.  They will also be linked to the provided sample, user, and project_id. 

Once data is uploaded it can be viewed in the [Crucible Web Explorer](https://crucible-graph-explorer-776258882599.us-central1.run.app/)!

*currently supported files include files smaller than 20GB with one of the following extensions: h5, tif, tiff, png, jpg, jpeg, csv, txt

### System requirements
- internet connection
- access to the local file system
- python >= 3.11
- (optional) [rclone](https://rclone.org/install/) — required only for cloud backup to Google Drive / GCS; the app will upload to Crucible without it
- (recommended) [uv](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer) `pipx install uv`

### Set Up
1. Clone this repository `git clone https://github.com/uachoudhry/crucible-spleem-upload-ui.git`
2. Create the uv virtual environment (alternatively, use the package manager of your choice and install from requirements-flask.txt)
```
cd crucible-spleem-upload-ui
uv sync
```
3. Configure crucible
```
crucible config init
```
4. (Optional) Configure rclone `rclone config`. You will need to configure 2 remotes:
    - mf-crucible google cloud storage.<br>
      ** Please name the mount ```mf-cloud-storage```<br>
      ** This will require access to the project. If you need access, please reach out to a member of the Molecular Foundry Data team.<br>
    - (optional) A google drive that you would like data from the instrument to be copied to.<br>
      ** Please name the mount in the format ```{instrument_name}-gdrive```

An example rclone configuration file is included below: 
```
[qspleem_microscope-gdrive]
type = drive
scope = drive
team_drive = <team-drive-id>
root_folder_id = 
token = {} # alternatively you can provide a service account key and add the service account email to your google shared drive.


[mf-cloud-storage]
type = google cloud storage
project_number = mf-crucible
service_account_file = <mf-crucible-service-account-key.json>
object_acl = projectPrivate
bucket_acl = projectPrivate
env_auth = true
bucket_policy_only = true
```
5. Run the app!

### Running the app
```
cd crucible-spleem-upload-ui
uv run python main.py
```

### Additional Details
- instrument_conf.py allows configuration of instrument specific details:
    - `DEFAULT_BROWSE_DIR` will set the default directory opened by the file picker
    - `IS_SESSION` should be set to True if you have a folder of data you want to upload as a dataset. This will create a `parent dataset` for the session as well as datasets for each qualifying file within the directory. The individual file based datasets will be linked to the `parent dataset` as children.
    - `INSTRUMENTS` is a list of the instruments that will appear as choices in a dropdown in the UI
    - `DEFAULT_INSTRUMENT_NAME` will be the pre-selected instrument value.
- To prevent accidental uploads of system-level directories, the selected folder must be at least 3 levels deep from the filesystem root (e.g. D:\Users\data\session). 


