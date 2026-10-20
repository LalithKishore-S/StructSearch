import os
import sys

from structsearch.interface.cli import main

try:
    code = main()
    sys.stdout.flush()
except BrokenPipeError:  # e.g. `... | head`: the reader closed early, exit quietly
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    code = 1
sys.exit(code)
