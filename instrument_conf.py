DEFAULT_BROWSE_DIR = ""  # Set to SPLEEM data directory, e.g. "G:\\Shared drives\\FeGd growth in SPLEEM\\Data"
IS_SESSION = True  # Session folder → one parent dataset + child dataset per file
INSTRUMENTS = ["qspleem_microscope"]  # Registered name in Crucible; update if renamed to 'qspleem'
DEFAULT_INSTRUMENT_NAME = "qspleem_microscope"
PRINT_BARCODE_ENABLED = False

INSTRUMENT_FLOWS = {
    "qspleem_microscope": "tem-session-upload/spleem-session-upload",  # flow-name/deployment-name: flow name matches upstream function tem_session_upload
}

ACCEPTABLE_FILE_TYPES = {'.h5', '.tif', '.tiff', '.png', '.csv', '.txt'}
