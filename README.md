# Project Modification History Statistics

Analyze per-project directory commit activity in a Git repo and export a CSV summary. Designed for .NET solutions, it discovers directories containing project files and counts commits by year, with optional ignore filters and customizable output.

- Script: `src/main.py` (cross‑platform)
- Windows wrapper: `proj-mod-hist-stats.cmd` (PowerShell/cmd friendly)
- Unix wrapper: `proj-mod-hist-stats.sh` (macOS/Linux)

## What it does
- Scans the repo for directories that contain any of: `.bproj`, `.csproj`, `.vcproj`, `.vcxproj`, `.xproj`, `.sln`.
- For each directory, runs a path‑scoped git log to count commits that touched files in that directory only.
- Aggregates counts for the last N years and an all‑time total.
- Writes a CSV named `<repo>_<branch>_<sha6>.csv` (names sanitized; sha is the latest commit’s short hash).
  - If `--project-type` is used and does not include all types, a suffix is appended with the selected types, e.g. `_csproj_vcxproj`.
  - By default, the CSV is written to the tool root directory unless you pass `-o/--output-dir`.

## Features
- Accurate per‑directory stats using `git -C <dir> log -- .` (scoped to that folder).
- Ignore filters: exclude directories by glob‑like patterns relative to the repo root.
- Verbosity controls: default info logs; `--verbose` for extra details; `--quiet` to suppress info.
- Deterministic CSV ordering (directories are sorted).
- No external Python dependencies (stdlib only).

## Requirements
- Git installed and available on PATH.
- Python 3.8+.
- A Git repository (the chosen root must contain a `.git` directory).
- Wrappers: Windows (`.cmd`) and macOS/Linux (`.sh`). The Python script itself works on all three OSes.

## Installation
Optional but recommended on Windows:
- Place both files in a tools folder (or the repo itself).
- Optionally create a venv at `.venv` in the same folder; the wrapper will prefer `.venv\Scripts\python.exe`.

No pip installs required.

## Usage
Note on PATH for examples:
- The wrapper command names used below (proj-mod-hist-stats / ./proj-mod-hist-stats.sh) assume this project’s folder is on your PATH. If not, run them via full path or from the script’s folder.
  - Windows: run with full path (e.g., `C:\...\.Net-Project-Modification-History\proj-mod-hist-stats.cmd ...`) or from that folder (`.\proj-mod-hist-stats ...`).
  - macOS/Linux: run the script directly from its folder (`./proj-mod-hist-stats.sh ...`) or add that folder to PATH.
  - Optional (PowerShell, current session only):
    ```powershell
    $env:Path = "C:\path\to\.Net-Project-Modification-History;" + $env:Path
    ```

### Windows wrapper (recommended on Windows)
From the repo root (or pass the repo root explicitly):

```powershell
# Use current directory as root
proj-mod-hist-stats --verbose

# Or pass the repo root explicitly
proj-mod-hist-stats C:\path\to\repo -y 5 -o C:\out -i "tests/*" -i src/Legacy
proj-mod-hist-stats --project-type .csproj,.vcxproj --verbose
```

Notes:
- If the first token starts with `-` or `/`, the wrapper defaults the root to the current directory.
- The output filename no longer accepts a custom prefix; it’s always `<repo>_<branch>_<sha6>.csv`.
- Set `PMH_DEBUG=1` for one run to print the composed command if you need to troubleshoot. This works for both the Windows and Unix wrappers.

### Unix wrapper (macOS/Linux)
```bash
# Use current directory as root
./proj-mod-hist-stats.sh --verbose

# Or pass the repo root explicitly
./proj-mod-hist-stats.sh /path/to/repo -y 5 -o /tmp/out -i 'tests/*' -i src/Legacy
./proj-mod-hist-stats.sh --project-type .csproj,.vcxproj --verbose
```

Notes:
- If the first token starts with `-`, the wrapper uses the current directory as the root.
- `PMH_DEBUG=1` will echo the resolved Python and arguments before running the script.

### Direct Python
```powershell
python src/main.py C:\path\to\repo -y 10 -o C:\out --verbose -i "tests/*,samples/*" --project-type .csproj,.vcxproj
```

## Options (Python CLI)
- `root_directory` (positional): Path to the repo root; must contain `.git`.
- `-y, --years N`: Number of years to analyze (default: 10).
- `-o, --output-dir DIR`: Output directory for the CSV (default: tool root directory). Will be created if it doesn't exist.
- `-i, --ignore PATTERN`: Relative path patterns to ignore (glob‑like). Can be repeated or comma‑separated, e.g. `-i "src/Legacy,tests/*"`.
- `--project-type`: One or more of `.bproj`, `.csproj`, `.vcproj`, `.vcxproj`, `.xproj`, `.sln`. Repeat or comma‑separate. Default: all. If not all are included, the filename gains a `_type` suffix (e.g., `_csproj_vcxproj`).
- `--quiet`: Suppress informational logs; warnings and the final summary still print.
- `--verbose`: Extra details during processing.

Note: `--quiet` and `--verbose` are mutually exclusive.

## Ignore patterns
- Patterns are evaluated against directory paths relative to the repo root, with `/` as the separator (paths are normalized).
- Matching uses glob‑style matching and a prefix check. Examples:
  - `-i "tests/*"` ignores any immediate child under `tests` (e.g., `tests/UnitTestProject`).
  - `-i packages/*` ignores top‑level children under `packages`.
  - You can repeat `-i` or use comma‑separated lists: `-i "samples/*,legacy/*" -i docs`.

## Output
- CSV filename: `<repo>_<branch>_<sha6>.csv`.
- If `--project-type` is used and not all types are included, the filename gets a suffix with the selected types (e.g., `_csproj_vcxproj`).
- If the initial write fails due to permissions or the file being locked, the tool will retry with a timestamp-suffixed filename, e.g. `<repo>_<branch>_<sha6>_YYYYMMDD_HHMMSS.csv`.
- After writing, the tool prints the CSV path along with the number of rows and columns.
- Columns: `Directory`, `ProjectType` (comma-separated when multiple), `Total`, one column per analyzed year (e.g., `2025, 2024, ...`), and cumulative columns `Acc_1..Acc_5` (sum of the most recent 1 to 5 years, respectively).
- `Directory` is the path relative to the repo root.
- `Total` is all‑time commits that touched files in that directory; yearly columns are counts within the chosen window.
- If HEAD is detached, the branch segment in the filename will be `detached`.

Example header:
```
Directory,ProjectType,Total,2025,2024,2023,2022,2021,Acc_1,Acc_2,Acc_3,Acc_4,Acc_5
```

## How it works (brief)
- For each project directory, the script executes:
  - `git -C <dir> log --pretty=format:%ad --date=short -- .`
- It extracts commit years, tallies them per directory for the last N years, and computes an all‑time total.
- The current branch name and short HEAD hash are used to name the CSV.

## Troubleshooting
- “The specified root directory … does not contain a .git directory”: pass the actual repo root, or run the wrapper from within the repo root.
- Patterns not matching: ensure you use forward slashes and quote globs in PowerShell, e.g. `-i "tests/*"`.
- Windows quoting: when using the wrapper from PowerShell, quoting globs (`"packages/*"`) avoids shell expansion.
- Verify Git is on PATH by running `git --version`.
- Permission denied or locked file: the tool will automatically retry with a timestamped filename. If it still fails, choose a different output folder via `-o/--output-dir` and ensure you have write permissions.

## Project layout
- `src/main.py`: Main CLI tool.
- `src/project_modification_analyzer.py`: Orchestrates scanning/filtering, builds headers, and writes CSV.
- `src/project.py`: Core analysis logic for scanning and tallying per-directory commits.
- `src/tools.py`: Helpers (logging, path normalization).
- `proj-mod-hist-stats.cmd`: Windows convenience wrapper that selects Python (prefers `.venv`), sets default root, and forwards all args (calls the script under `src/`).
- `proj-mod-hist-stats.sh`: Unix/macOS wrapper that prefers `.venv/bin/python`, defaults root when the first token is an option, and forwards all args (calls the script under `src/`).

---

If you have ideas for enhancements (e.g., more project types, additional output formats, or tests), feel free to open an issue or PR once this is on GitHub.
