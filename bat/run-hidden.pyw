"""Run a .bat file without a console window, e.g. from the Windows Startup folder.

Usage: pythonw run-hidden.pyw path\\to\\script.bat
"""

import subprocess
import sys

result = subprocess.run(["cmd", "/c", sys.argv[1]], creationflags=subprocess.CREATE_NO_WINDOW)
sys.exit(result.returncode)
