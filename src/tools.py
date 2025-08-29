import os
import subprocess
from typing import List

# Global verbosity flag; set in main(); default to verbose output
QUIET = False
VERBOSE = False


def nprint(*args, **kwargs):
    if not QUIET:
        print(*args, **kwargs)


def vprint(*args, **kwargs):
    if VERBOSE:
        print(*args, **kwargs)


def normalize_rel(path: str) -> str:
    return os.path.normpath(path).replace("\\", "/")


def subprocess_check(cmd: List[str]) -> subprocess.CompletedProcess:
    """
    Run a subprocess command in the given working directory.
    Returns the CompletedProcess instance.
    Raises subprocess.CalledProcessError on failure.
    """
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
