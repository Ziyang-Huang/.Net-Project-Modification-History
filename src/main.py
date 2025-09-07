import argparse
import os
from datetime import datetime
from typing import List, Tuple

import tools as _tools
from project import Project
from project_modification_analyzer import ProjectModificationAnalyzer
from tools import normalize_rel, nprint


def _validate_root_directory(path: str) -> str:
    if not os.path.isdir(path):
        raise argparse.ArgumentTypeError(f"The specified root directory '{path}' does not exist.")
    if not os.path.isdir(os.path.join(path, ".git")):
        raise argparse.ArgumentTypeError(f"The specified root directory '{path}' does not contain a .git directory.")
    return os.path.abspath(path)


def _validate_year_range(value: str) -> int:
    try:
        ivalue = int(value)
        if ivalue < 1:
            raise argparse.ArgumentTypeError("Year range must be an integer greater than or equal to 1.")
        return ivalue
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Year range must be an integer greater than or equal to 1.") from exc


def _validate_output_directory(path: str) -> str:
    if os.path.isfile(path):
        raise argparse.ArgumentTypeError(
            f"The specified output directory '{path}' is not a directory or does not exist."
        )
    return os.path.abspath(path)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Analyze .bproj/.csproj/.vcproj/.vcxproj/.xproj/.sln directory modification history using Git."
    )
    parser.add_argument(
        "root_directory",
        type=_validate_root_directory,
        help="Root directory of the .NET codebase (must contain .git)",
    )
    parser.add_argument(
        "-y",
        "--years",
        type=_validate_year_range,
        default=10,
        help="Number of years to analyze (default: 10)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=_validate_output_directory,
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="Directory to write the CSV file (default: tool root directory)",
    )
    parser.add_argument(
        "--project-type",
        action="append",
        default=[],
        help=(
            "Project types to include (choose from: .bproj, .csproj, .vcproj, .vcxproj, .xproj, .sln). "
            "Can be repeated or comma-separated. Default: all"
        ),
    )
    parser.add_argument(
        "-i",
        "--ignore",
        action="append",
        default=[],
        help=(
            "Relative path patterns to ignore (glob). "
            "Can be specified multiple times or comma-separated, e.g. 'src/Legacy,tests/*'"
        ),
    )
    # Place verbosity controls at the end and make them mutually exclusive
    vgroup = parser.add_mutually_exclusive_group()
    vgroup.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational logs; only output results and warnings",
    )
    vgroup.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logs (additional details during processing)",
    )
    return parser.parse_args()


def _flatten_types(values: List[str]) -> List[str]:
    items: List[str] = []
    for v in values or []:
        if not v:
            continue
        parts = [p.strip() for p in str(v).split(",") if p.strip()]
        items.extend(parts)
    return items


def _normalize_types(types: List[str]) -> List[str]:
    norm: List[str] = []
    for t in types:
        t_low = t.lower()
        if not t_low.startswith("."):
            t_low = "." + t_low
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
            raise SystemExit(
                f"Invalid --project-type values: {', '.join(invalid)}. Allowed: {', '.join(Project.ALLOWED_TYPES)}"
            )
        selected_exts: Tuple[str, ...] = tuple(valid)
    else:
        selected_exts = tuple(Project.ALLOWED_TYPES)
    return selected_exts


def get_year_window(year_range: int) -> List[str]:
    """Return a list of year strings for the last N natural years (current year first)."""
    current_year = datetime.now().year
    return [str(current_year - i) for i in range(year_range)]


def flatten_ignore_args(ignore_args: List[str]) -> List[str]:
    flattened_args: List[str] = []
    for item in ignore_args or []:
        if not item:
            continue
        parts = [p.strip() for p in str(item).split(",") if p.strip()]
        flattened_args.extend(parts)
    return flattened_args


def main():
    start_time = datetime.now()

    args = parse_arguments()
    # Set verbosity flags on the shared tools module
    _tools.QUIET = bool(args.quiet)
    _tools.VERBOSE = bool(args.verbose)

    # Resolve project types
    selected_exts = select_project_types(args.project_type)
    years = get_year_window(args.years)
    ignore_patterns = flatten_ignore_args(args.ignore)

    analyzer = ProjectModificationAnalyzer(args.root_directory, years, selected_exts, ignore_patterns)
    analyzer.analyze(args.output_dir)

    elapsed = (datetime.now() - start_time).total_seconds()
    nprint(f"Done in {elapsed:.2f}s")


if __name__ == "__main__":
    main()
