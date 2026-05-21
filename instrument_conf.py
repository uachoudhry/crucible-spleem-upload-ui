DEFAULT_BROWSE_DIR = ""  # Set to a path like "/data/sessions" to default the file picker
# True  = pick a folder; create parent session dataset + one child dataset per file inside
# False = pick one or more files; each becomes its own standalone dataset (or insitu, per instrument)
IS_SESSION = True
INSTRUMENTS=["titanx", "themis", "team1",  "team05", 'spectre', "insitu_pl"] # you can add your instrument here
DEFAULT_INSTRUMENT_NAME = 'titanx'

# Maps instrument names to their Prefect deployment name (flow-name/deployment-name)
INSTRUMENT_FLOWS = {
    "insitu_pl": "insitu-upload/insitu-upload",
    "titanx": "tem-session-upload/tem-session-upload",  # add when ready
}

PRINT_BARCODE_ENABLED = False
ACCEPTABLE_FILE_TYPES = {'.emd', '.dm3', '.dm4', '.bcf', '.ser', '.mcr', '.h5'}
'''
To enable barcode printing: 
- set PRINT_BARCODE_ENABLED to True
- Connect a brother pt-d610bt label printer to the computer running this code, and set the printer name in the print_label function in backend.py
- Install the required libraries: uv add pywin32
- Install printer driver from here: https://support.brother.com/g/b/downloadtop.aspx?c=us&lang=en&prod=d610bteus
- Find the printer in settings under printers and scanners and note the exact name (e.g. "Brother PT-D610BT")
- Download the brothers SDK for Windows B-pac (made a free account)
- Set printer settings through windows to match the tape type and size that you want to print (https://docs.google.com/presentation/d/1vSS1Xp0fzIwflpj50vx5LOO9MuW7FtZhLS1EQ7D4opI/edit?usp=sharing)
'''

