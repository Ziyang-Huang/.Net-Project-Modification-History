import os


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
    return os.path.normpath(path).replace('\\', '/')