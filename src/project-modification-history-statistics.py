import os
import csv
import subprocess
import argparse
import sys
import re

from datetime import datetime
from typing import List, Set, Tuple, Optional

from project import Project
from tools import QUIET, VERBOSE, nprint, vprint, normalize_rel


def _validate_root_directory(path):
    if not os.path.isdir(path):
        raise argparse.ArgumentTypeError(f"The specified root directory '{path}' does not exist.")
    if not os.path.isdir(os.path.join(path, ".git")):
        raise argparse.ArgumentTypeError(f"The specified root directory '{path}' does not contain a .git directory.")
    return os.path.abspath(path)

def _validate_year_range(value):
    try:
        ivalue = int(value)
        if ivalue < 1:
            raise argparse.ArgumentTypeError("Year range must be an integer greater than or equal to 1.")
        return ivalue
    except ValueError:
        raise argparse.ArgumentTypeError("Year range must be an integer greater than or equal to 1.")

def parse_arguments():
    parser = argparse.ArgumentParser(description="Analyze .bproj/.csproj/.vcxproj/.xproj/.sln directory modification history using Git.")
    parser.add_argument("root_directory", type=_validate_root_directory, help="Root directory of the .NET codebase (must contain .git)")
    parser.add_argument("-y", "--years", type=_validate_year_range, default=10, help="Number of years to analyze (default: 10)")
    parser.add_argument("-o", "--output-dir", type=str, default=None, help="Directory to write the CSV file (default: script directory)")
    parser.add_argument(
        "--project-type",
        action="append",
        default=[],
        help=(
            "Project types to include (choose from: .bproj, .csproj, .vcxproj, .xproj, .sln). "
            "Can be repeated or comma-separated. Default: all"
        ),
    )
    parser.add_argument(
        "-i", "--ignore", action="append", default=[],
        help=(
            "Relative path patterns to ignore (glob). "
            "Can be specified multiple times or comma-separated, e.g. 'src/Legacy,tests/*'"
        ),
    )
    # Place verbosity controls at the end and make them mutually exclusive
    vgroup = parser.add_mutually_exclusive_group()
    vgroup.add_argument("--quiet", action="store_true", help="Suppress informational logs; only output results and warnings")
    vgroup.add_argument("--verbose", action="store_true", help="Enable verbose logs (additional details during processing)")
    return parser.parse_args()

def _flatten_types(values: List[str]) -> List[str]:
    items: List[str] = []
    for v in values or []:
        if not v:
            continue
        parts = [p.strip() for p in str(v).split(',') if p.strip()]
        items.extend(parts)
    return items

def _normalize_types(types: List[str]) -> List[str]:
    norm: List[str] = []
    for t in types:
        t_low = t.lower()
        if not t_low.startswith('.'):
            t_low = '.' + t_low
        norm.append(t_low)
    return norm

def _validate_types(types: List[str]) -> Tuple[List[str], List[str]]:
    invalid = sorted(set(types) - set(Project.ALLOWED_TYPES))
    valid = sorted(set(types) - set(invalid))
    return valid, invalid

def select_project_types(raw_values: List[str]) -> Tuple[str, ...]:
    raw_types = _flatten_types(raw_values)
    if raw_types:
        norm = _normalize_types(raw_types)
        valid, invalid = _validate_types(norm)
        if invalid:
            raise SystemExit(f"Invalid --project-type values: {', '.join(invalid)}. Allowed: {', '.join(Project.ALLOWED_TYPES)}")
        selected_exts: Tuple[str, ...] = tuple(valid)
    else:
        selected_exts = tuple(Project.ALLOWED_TYPES)
    return selected_exts

def get_year_window(year_range: int) -> List[str]:
    """Return a list of year strings for the last N natural years (current year first)."""
    current_year = datetime.now().year
    return [str(current_year - i) for i in range(year_range)]

def flatten_ignore_args(ignore_args: List[str]) -> List[str]:
    patterns: List[str] = []
    for item in ignore_args or []:
        if not item:
            continue
        parts = [p.strip() for p in str(item).split(',') if p.strip()]
        patterns.extend(parts)
    # normalize pattern slashes
    return [normalize_rel(p) for p in patterns]

def _find_extensions(filenames: List[str], selected_exts: Tuple[str, ...]) -> Set[str]:
    exts = set()
    for filename in filenames:
        _, ext = os.path.splitext(filename.lower())
        if ext in selected_exts:
            exts.add(ext)
    return exts

def find_projects(root_dir: str, selected_exts: Tuple[str, ...], years: List[str], ignore_patterns: List[str]) -> List[Project]:
    projects = []
    for dirpath, _, filenames in os.walk(root_dir):
        exts = _find_extensions(filenames, selected_exts)
        if exts:
            projects.append(Project(root_dir, dirpath, exts, years, ignore_patterns))
    return projects

def aggregate_modifications(projects: List[Project]) -> Tuple[List[dict], List[str]]:
    data: List[dict] = []
    total_dirs = len(projects)
    for idx, project in enumerate(projects, start=1):
        nprint(f"[{idx}/{total_dirs}] Analyzing: {project.rel_dir}")
        row = project.analyze_directory()
        data.append(row)
    return data

def _sanitize_branch_name(name: str) -> str:
    # Replace path separators and spaces; allow alnum, dot, underscore, dash
    safe = name.replace(os.sep, "-").replace("/", "-")
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", safe)
    return safe or "unknown"

def get_repo_branch_and_head(root_dir: str) -> Tuple[str, str]:
    """Return (branch, short_sha6) for the repo at root_dir. On failure, ('unknown','unknown')."""
    try:
        # Prefer branch --show-current; fallback to rev-parse
        r1 = subprocess.run([
            "git", "-C", root_dir, "branch", "--show-current"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        branch = r1.stdout.strip()
        if not branch:
            r2 = subprocess.run([
                "git", "-C", root_dir, "rev-parse", "--abbrev-ref", "HEAD"
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if r2.returncode == 0:
                branch = r2.stdout.strip()
        if branch.upper() == "HEAD" or not branch:
            branch = "detached"

        r3 = subprocess.run([
            "git", "-C", root_dir, "rev-parse", "--short=6", "HEAD"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if r3.returncode != 0:
            print(f"Warning: git rev-parse failed at '{root_dir}': {r3.stderr.strip()}", file=sys.stderr)
            return ("unknown", "unknown")
        sha = r3.stdout.strip()
        return (_sanitize_branch_name(branch), sha)
    except Exception as exc:
        print(f"Warning: git query exception at '{root_dir}': {exc}", file=sys.stderr)
        return ("unknown", "unknown")

def _build_filename_suffix(selected_exts: Tuple[str, ...]) -> str:
    sel_norm = sorted(selected_exts or ())
    all_norm = sorted(Project.ALLOWED_TYPES)
    if sel_norm and sel_norm != all_norm:
        tokens = [e.lstrip(".") for e in sel_norm]
        return "_" + "_".join(tokens)
    return ""

def determine_output_path(root_dir: str, output_dir: Optional[str], selected_exts: Tuple[str, ...]) -> str:
    branch, sha = get_repo_branch_and_head(root_dir)
    repo_name = os.path.basename(os.path.normpath(root_dir)) or "repo"
    repo_safe = _sanitize_branch_name(repo_name)
    suffix = _build_filename_suffix(selected_exts)
    filename = f"{repo_safe}_{branch}_{sha}{suffix}.csv"
    out_dir = output_dir if output_dir else os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, filename)

def build_headers(years: List[str], acc_max: int = Project.ACC_MAX_YEARS) -> List[str]:
    return ["Directory", "ProjectType", "Total"] + years + [f"Acc_{i}" for i in range(1, acc_max + 1)]

def write_csv_rows(out_path: str, headers: List[str], data: List[dict]) -> None:
    with open(out_path, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in data:
            writer.writerow(row)

def write_csv(data: List[dict], years: List[str], root_dir: str, output_dir: str, selected_exts: Tuple[str, ...]):
    out_path = determine_output_path(root_dir, output_dir, selected_exts)
    headers = build_headers(years, min(Project.ACC_MAX_YEARS, len(years)))
    write_csv_rows(out_path, headers, data)
    print(f"\nCSV created: '{out_path}'\n    rows: {len(data)}\n    columns: {len(headers)}")

def filter_projects(projects: List[Project]) -> Tuple[List[Project], List[Project]]:
    filtered: List[Project] = [proj for proj in projects if not proj.is_ignored]
    ignored: List[Project] = [proj for proj in projects if proj.is_ignored]
    return filtered, ignored

def main():
    start_time = datetime.now()

    args = parse_arguments()
    global QUIET
    QUIET = bool(args.quiet)
    global VERBOSE
    VERBOSE = bool(args.verbose)

    # Resolve project types
    selected_exts = select_project_types(args.project_type)
    years = get_year_window(args.years)
    ignore_patterns = flatten_ignore_args(args.ignore)
    nprint(f"Starting analysis\n    Root: {args.root_directory}\n    Time Range: past [{args.years}] years\n    Project Types: {', '.join(selected_exts)}\n")

    projects = find_projects(args.root_directory, selected_exts, years, ignore_patterns)
    nprint(f"Found {len(projects)} project directories before filtering")

    # Apply ignore filters (relative to root)
    projects, ignored = filter_projects(projects)
    if ignored:
        nprint(f"    Ignored {len(ignored)} directories via patterns: {', '.join(ignore_patterns)}")
        vprint("  -> " + " | ".join(sorted(normalize_rel(p.rel_dir) for p in ignored)))

    if not projects:
        print("\nNo project directories (.bproj/.csproj/.vcxproj/.xproj/.sln) found. Exiting.")
        return

    nprint(f"    Using {len(projects)} project directories after filtering\n")

    data = aggregate_modifications(projects)
    write_csv(data, years, args.root_directory, args.output_dir, selected_exts)

    elapsed = (datetime.now() - start_time).total_seconds()
    nprint(f"Done in {elapsed:.2f}s")

if __name__ == "__main__":
    main()
