import os
import csv
import subprocess
from datetime import datetime
import argparse
import sys
import re
import fnmatch
from typing import List, Tuple, Dict, Optional

# Global verbosity flag; set in main(); default to verbose output
QUIET = False
VERBOSE = False

# Supported project types and accumulator configuration
ALLOWED_TYPES: List[str] = [".bproj", ".csproj", ".vcxproj", ".xproj"]
ACC_MAX_YEARS = 5

def nprint(*args, **kwargs):
    if not QUIET:
        print(*args, **kwargs)

def vprint(*args, **kwargs):
    if VERBOSE:
        print(*args, **kwargs)

def validate_root_directory(path):
    if not os.path.isdir(path):
        raise argparse.ArgumentTypeError(f"The specified root directory '{path}' does not exist.")
    if not os.path.isdir(os.path.join(path, ".git")):
        raise argparse.ArgumentTypeError(f"The specified root directory '{path}' does not contain a .git directory.")
    return os.path.abspath(path)

def validate_year_range(value):
    try:
        ivalue = int(value)
        if ivalue < 1:
            raise argparse.ArgumentTypeError("Year range must be an integer greater than or equal to 1.")
        return ivalue
    except ValueError:
        raise argparse.ArgumentTypeError("Year range must be an integer greater than or equal to 1.")

def parse_arguments():
    parser = argparse.ArgumentParser(description="Analyze .bproj/.csproj/.vcxproj/.xproj directory modification history using Git.")
    parser.add_argument("root_directory", type=validate_root_directory, help="Root directory of the .NET codebase (must contain .git)")
    parser.add_argument("-y", "--years", type=validate_year_range, default=10, help="Number of years to analyze (default: 10)")
    parser.add_argument("-o", "--output-dir", type=str, default=None, help="Directory to write the CSV file (default: script directory)")
    parser.add_argument(
        "--project-type",
        action="append",
        default=[],
        help=(
            "Project types to include (choose from: .bproj, .csproj, .vcxproj, .xproj). "
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

def get_year_window(year_range: int) -> List[str]:
    """Return a list of year strings for the last N natural years (current year first)."""
    current_year = datetime.now().year
    return [str(current_year - i) for i in range(year_range)]

def find_project_directories(root_dir: str, exts: Tuple[str, ...]) -> List[str]:
    proj_dirs = set()
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.lower().endswith(exts):
                proj_dirs.add(dirpath)
                break
    return sorted(list(proj_dirs))

def tally_year_counts(years_modified: List[str], years: List[str]) -> Dict[str, int]:
    """Count commits per target year from a list of commit years."""
    year_counts = {year: 0 for year in years}
    for y in years_modified:
        if y in year_counts:
            year_counts[y] += 1
    return year_counts

def compute_accumulators(year_counts: Dict[str, int], years: List[str], max_k: int = ACC_MAX_YEARS) -> Dict[str, int]:
    """Compute cumulative sums for the most recent 1..max_k years based on the provided years order."""
    vals = [year_counts[y] for y in years]
    acc: Dict[str, int] = {}
    running = 0
    for k in range(1, max_k + 1):
        if k <= len(vals):
            running += vals[k - 1]
        acc[f"Acc_{k}"] = running
    return acc

def analyze_directory(dir_path: str, years: List[str], root_dir: str, idx: int, total_dirs: int) -> Dict[str, int]:
    """Analyze a single project directory and return the CSV row dict."""
    nprint(f"[{idx}/{total_dirs}] Analyzing: {dir_path}")
    years_modified = get_git_modification_years(dir_path)
    year_counts = tally_year_counts(years_modified, years)
    total_modifications = len(years_modified)
    rel_dir = os.path.relpath(dir_path, root_dir)
    row: Dict[str, int] = {"Directory": rel_dir, "Total": total_modifications}  # type: ignore[assignment]
    # Per-year counts
    for y in years:
        row[y] = year_counts[y]  # type: ignore[index]
    # Accumulators
    row.update(compute_accumulators(year_counts, years))
    nprint(f"    -> commits(all-time in dir): {total_modifications}; in-range: {sum(year_counts.values())}")
    return row

def get_git_modification_years(directory: str) -> List[str]:
    """
    Return a list of years for commits that modified files under the given directory only.
    Uses: git -C <directory> log --pretty=format:%ad --date=short -- .
    On failure, prints a warning and returns an empty list.
    """
    try:
        result = subprocess.run(
            ["git", "-C", directory, "log", "--pretty=format:%ad", "--date=short", "--", "."],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            print(f"Warning: git log failed for '{directory}': {result.stderr.strip()}", file=sys.stderr)
            return []
        dates = result.stdout.splitlines()
        years = [date.split("-")[0] for date in dates if date]
        return years
    except Exception as exc:
        print(f"Warning: git log exception for '{directory}': {exc}", file=sys.stderr)
        return []

def aggregate_modifications(proj_dirs: List[str], year_range: int, root_dir: str) -> Tuple[List[dict], List[str]]:
    years = get_year_window(year_range)
    data: List[dict] = []
    total_dirs = len(proj_dirs)
    for idx, d in enumerate(proj_dirs, start=1):
        row = analyze_directory(d, years, root_dir, idx, total_dirs)
        data.append(row)
    return data, years

def _normalize_rel(path: str) -> str:
    return os.path.normpath(path).replace('\\', '/')

def _flatten_ignore_args(ignore_args: List[str]) -> List[str]:
    patterns: List[str] = []
    for item in ignore_args or []:
        if not item:
            continue
        parts = [p.strip() for p in str(item).split(',') if p.strip()]
        patterns.extend(parts)
    # normalize pattern slashes
    return [_normalize_rel(p) for p in patterns]

def _is_ignored(rel_dir: str, patterns: List[str]) -> bool:
    rel = _normalize_rel(rel_dir)
    for pat in patterns:
        # glob match or directory prefix match
        if fnmatch.fnmatchcase(rel, pat):
            return True
        if rel == pat or rel.startswith(pat + '/'):
            return True
    return False

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

def _build_filename_suffix(selected_exts: List[str]) -> str:
    sel_norm = sorted(selected_exts or [])
    all_norm = sorted(ALLOWED_TYPES)
    if sel_norm and sel_norm != all_norm:
        tokens = [e.lstrip(".") for e in sel_norm]
        return "_" + "_".join(tokens)
    return ""

def determine_output_path(root_dir: str, output_dir: Optional[str], selected_exts: List[str]) -> str:
    branch, sha = get_repo_branch_and_head(root_dir)
    repo_name = os.path.basename(os.path.normpath(root_dir)) or "repo"
    repo_safe = _sanitize_branch_name(repo_name)
    suffix = _build_filename_suffix(selected_exts)
    filename = f"{repo_safe}_{branch}_{sha}{suffix}.csv"
    out_dir = output_dir if output_dir else os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, filename)

def build_headers(years: List[str], acc_max: int = ACC_MAX_YEARS) -> List[str]:
    return ["Directory", "Total"] + years + [f"Acc_{i}" for i in range(1, acc_max + 1)]

def write_csv_rows(out_path: str, headers: List[str], data: List[dict]) -> None:
    with open(out_path, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in data:
            writer.writerow(row)

def write_csv(data: List[dict], years: List[str], root_dir: str, output_dir: str, selected_exts: List[str]) -> str:
    out_path = determine_output_path(root_dir, output_dir, selected_exts)
    headers = build_headers(years)
    write_csv_rows(out_path, headers, data)
    print(f"CSV created: '{out_path}' | rows: {len(data)} | columns: {len(headers)}")
    return out_path

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
    invalid = sorted(set(types) - set(ALLOWED_TYPES))
    valid = sorted(set(types) - set(invalid))
    return valid, invalid

def select_project_types(raw_values: List[str]) -> Tuple[Tuple[str, ...], List[str]]:
    raw_types = _flatten_types(raw_values)
    if raw_types:
        norm = _normalize_types(raw_types)
        valid, invalid = _validate_types(norm)
        if invalid:
            raise SystemExit(f"Invalid --project-type values: {', '.join(invalid)}. Allowed: {', '.join(ALLOWED_TYPES)}")
        selected_exts: Tuple[str, ...] = tuple(valid)
    else:
        selected_exts = tuple(ALLOWED_TYPES)
    return selected_exts, list(selected_exts)

def filter_project_dirs(proj_dirs: List[str], root_dir: str, ignore_patterns: List[str]) -> Tuple[List[str], List[str]]:
    if not ignore_patterns:
        return proj_dirs, []
    filtered: List[str] = []
    ignored_list: List[str] = []
    for d in proj_dirs:
        rel = os.path.relpath(d, root_dir)
        if _is_ignored(rel, ignore_patterns):
            ignored_list.append(rel)
        else:
            filtered.append(d)
    return filtered, ignored_list

def main():
    args = parse_arguments()
    global QUIET
    QUIET = bool(args.quiet)
    global VERBOSE
    VERBOSE = bool(args.verbose)
    # Resolve project types
    selected_exts, sel_list = select_project_types(args.project_type)
    start_time = datetime.now()
    nprint(f"Starting analysis | root: {args.root_directory} | years: {args.years}")
    nprint(f"Scanning for project directories matching: {', '.join(selected_exts)}...")
    proj_dirs = find_project_directories(args.root_directory, selected_exts)
    nprint(f"Found {len(proj_dirs)} project directories before filtering")

    # Apply ignore filters (relative to root)
    ignore_patterns = _flatten_ignore_args(args.ignore)
    proj_dirs, ignored_list = filter_project_dirs(proj_dirs, args.root_directory, ignore_patterns)
    if ignore_patterns and not QUIET:
        nprint(f"Ignored {len(ignored_list)} directories via patterns: {', '.join(ignore_patterns)}")
        if VERBOSE and ignored_list:
            nprint("  -> " + " | ".join(sorted(_normalize_rel(x) for x in ignored_list)))

    nprint(f"Using {len(proj_dirs)} project directories after filtering")
    if not proj_dirs:
        print("No project directories (.bproj/.csproj/.vcxproj/.xproj) found. Exiting.")
        return
    data, years = aggregate_modifications(proj_dirs, args.years, args.root_directory)
    out_file = write_csv(data, years, args.root_directory, args.output_dir, sel_list)
    elapsed = (datetime.now() - start_time).total_seconds()
    nprint(f"Done in {elapsed:.2f}s")

if __name__ == "__main__":
    main()
