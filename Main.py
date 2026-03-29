import subprocess
import sys
from pathlib import Path
 
base = Path(__file__).parent
 
subprocess.Popen([sys.executable, str(base / "skeletonTracking.py")])
subprocess.Popen([sys.executable, str(base / "Config.py")])
 