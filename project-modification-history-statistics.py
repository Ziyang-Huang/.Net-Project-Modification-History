import os
import csv
import subprocess
from datetime import datetime
import argparse
import sys
import re
import fnmatch
from typing import List, Tuple

# Global verbosity flag; set in main(); default to verbose output
QUIET = False
VERBOSE = False

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
    parser = argparse.ArgumentParser(description="Analyze .bproj/.csproj/.vcxproj directory modification history using Git.")
    parser.add_argument("root_directory", type=validate_root_directory, help="Root directory of the .NET codebase (must contain .git)")
    parser.add_argument("-y", "--years", type=validate_year_range, default=10, help="Number of years to analyze (default: 10)")
    parser.add_argument("-o", "--output-dir", type=str, default=None, help="Directory to write the CSV file (default: script directory)")
    parser.add_argument(
        "--project-type",
        action="append",
        default=[],
        help=(
            "Project types to include (choose from: .bproj, .csproj, .vcxproj). "
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

def find_project_directories(root_dir: str, exts: Tuple[str, ...]) -> List[str]:
    proj_dirs = set()
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.lower().endswith(exts):
                proj_dirs.add(dirpath)
                break
    return sorted(list(proj_dirs))

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
    current_year = datetime.now().year
    years = [str(current_year - i) for i in range(year_range)]
    data = []

    total_dirs = len(proj_dirs)
    for idx, dir in enumerate(proj_dirs, start=1):
        nprint(f"[{idx}/{total_dirs}] Analyzing: {dir}")
        year_counts = {year: 0 for year in years}
        years_modified = get_git_modification_years(dir)
        for y in years_modified:
            if y in year_counts:
                year_counts[y] += 1
        total_modifications = len(years_modified)
        rel_dir = os.path.relpath(dir, root_dir)
        row = {"Directory": rel_dir, "Total": total_modifications}
        row.update({year: year_counts[year] for year in years})
        data.append(row)
        nprint(f"    -> commits(all-time in dir): {total_modifications}; in-range: {sum(year_counts.values())}")

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

def write_csv(data: List[dict], years: List[str], root_dir: str, output_dir: str, selected_exts: List[str]) -> str:
    branch, sha = get_repo_branch_and_head(root_dir)
    repo_name = os.path.basename(os.path.normpath(root_dir)) or "repo"
    repo_safe = _sanitize_branch_name(repo_name)
    # Determine optional project-type suffix if not using all types (exactly these three are supported)
    allowed_all = [".bproj", ".csproj", ".vcxproj"]
    sel_norm = sorted(selected_exts or [])
    all_norm = sorted(allowed_all)
    suffix = ""
    if sel_norm and sel_norm != all_norm:
        # Append normalized tokens without dots, joined by '_'
        tokens = [e.lstrip(".") for e in sel_norm]
        suffix = "_" + "_".join(tokens)
    filename = f"{repo_safe}_{branch}_{sha}{suffix}.csv"
    # Resolve output directory
    out_dir = output_dir if output_dir else os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, filename)
    headers = ["Directory", "Total"] + years
    with open(out_path, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in data:
            writer.writerow(row)
    print(f"CSV created: '{out_path}' | rows: {len(data)} | columns: {len(headers)}")
    return out_path

def main():
    args = parse_arguments()
    global QUIET
    QUIET = bool(args.quiet)
    global VERBOSE
    VERBOSE = bool(args.verbose)
    # Resolve project types (only these are allowed)
    allowed_types = [".bproj", ".csproj", ".vcxproj"]
    def _flatten_types(values: List[str]) -> List[str]:
        items: List[str] = []
        for v in values or []:
            if not v:
                continue
            parts = [p.strip() for p in str(v).split(',') if p.strip()]
            items.extend(parts)
        return items
    raw_types = _flatten_types(args.project_type)
    if raw_types:
        norm = []
        for t in raw_types:
            t_low = t.lower()
            if not t_low.startswith('.'):
                t_low = '.' + t_low
            norm.append(t_low)
        # validate
        invalid = sorted(set(norm) - set(allowed_types))
        if invalid:
            raise SystemExit(f"Invalid --project-type values: {', '.join(invalid)}. Allowed: {', '.join(allowed_types)}")
        selected_exts: Tuple[str, ...] = tuple(sorted(set(norm)))
    else:
        selected_exts = tuple(allowed_types)
    start_time = datetime.now()
    nprint(f"Starting analysis | root: {args.root_directory} | years: {args.years}")
    nprint(f"Scanning for project directories matching: {', '.join(selected_exts)}...")
    proj_dirs = find_project_directories(args.root_directory, selected_exts)
    nprint(f"Found {len(proj_dirs)} project directories before filtering")

    # Apply ignore filters (relative to root)
    ignore_patterns = _flatten_ignore_args(args.ignore)
    if ignore_patterns:
        filtered = []
        ignored_list = []
        for d in proj_dirs:
            rel = os.path.relpath(d, args.root_directory)
            if _is_ignored(rel, ignore_patterns):
                ignored_list.append(rel)
            else:
                filtered.append(d)
        if not QUIET:
            nprint(f"Ignored {len(ignored_list)} directories via patterns: {', '.join(ignore_patterns)}")
            if VERBOSE and ignored_list:
                nprint("  -> " + " | ".join(sorted(_normalize_rel(x) for x in ignored_list)))
        proj_dirs = filtered

    nprint(f"Using {len(proj_dirs)} project directories after filtering")
    if not proj_dirs:
        print("No project directories (.bproj/.csproj/.vcxproj) found. Exiting.")
        return
    data, years = aggregate_modifications(proj_dirs, args.years, args.root_directory)
    out_file = write_csv(data, years, args.root_directory, args.output_dir, list(selected_exts))
    elapsed = (datetime.now() - start_time).total_seconds()
    nprint(f"Done in {elapsed:.2f}s")

if __name__ == "__main__":
    main()
