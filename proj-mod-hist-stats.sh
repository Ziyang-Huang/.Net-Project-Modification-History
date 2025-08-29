#!/usr/bin/env bash

# Determine script directory
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Prefer the workspace venv's python if it exists
PY="$SCRIPT_DIR/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  # Fallback to common Python executables
  if command -v python3 >/dev/null 2>&1; then
    PY="python3"
  elif command -v python >/dev/null 2>&1; then
    PY="python"
  elif command -v py >/dev/null 2>&1; then
    PY="py"
  else
    PY="python"
  fi
fi

print_help() {
  local prog
  prog="$(basename "$0")"
  cat <<EOF
Usage: $prog [ROOT_DIR] [options]

  ROOT_DIR  Path to the repo root (must contain .git) (default: current directory)
  options   Passed through to project-modification-history-statistics.py

Common options:
  -y N            Number of years to analyze (default: 10)
  -o DIR          Output directory for CSV (default: script directory)
  -i PATTERN      Ignore relative path patterns (glob; can repeat or comma-separate)
  --project-type  Project types to include: .bproj, .csproj, .vcxproj, .xproj, .sln (repeat or comma-separated)
  --quiet | --verbose  Quiet or verbose mode (mutually exclusive; place last)

Notes:
  - If the first token starts with '-', the wrapper uses the current directory as ROOT.

Examples:
  $prog                        # uses current directory
  $prog /path/to/repo -y 5 -o /tmp/out -i src/Legacy -i 'tests/*' --verbose
  $prog --project-type .csproj,.vcxproj --verbose
EOF
}

# Help shortcuts
case "${1-}" in
  -h|--help|-?)
    print_help
    exit 0
    ;;
esac

# Determine ROOT and ARGS
ROOT=""
if [[ $# -eq 0 ]]; then
  ROOT="$PWD"
else
  FIRST="$1"
  if [[ "$FIRST" == -* ]]; then
    ROOT="$PWD"
  else
    ROOT="$FIRST"
    shift
  fi
fi

# No filename prefix is used anymore; output name is <repo>_<branch>_<sha6>.csv

# Optional debug: set PMH_DEBUG=1 to print the composed command
if [[ "${PMH_DEBUG-}" == "1" ]]; then
  echo "PY: $PY"
  echo "ROOT: \"$ROOT\""
  echo "ARGS: $*"
  echo "(no extra opts)"
fi

# Call Python with original args preserved
"$PY" "$SCRIPT_DIR/src/project-modification-history-statistics.py" "$ROOT" "$@"
EXITCODE=$?
if [[ $EXITCODE -ne 0 ]]; then
  echo "Script exited with code $EXITCODE."
fi
exit $EXITCODE
