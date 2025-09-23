import os
import subprocess
import sys
import csv
from typing import Dict, List, Tuple

from tools import normalize_rel, nprint, vprint, subprocess_check


class Project:
    # Supported project types and accumulator configuration
    SUPPORTED_TYPES: Tuple[str, ...] = (".bproj", ".cbproj", ".csproj", ".dtproj", ".fsproj", ".groupproj", ".iscopeproj", ".jsproj", ".nugetproj", ".pbxproj", ".proj", ".pyproj", ".rptproj", ".scopeproj", ".shfbproj", ".sln_bproj", ".smproj", ".sqlproj", ".vbproj", ".vcproj", ".vcxproj", ".vdproj", ".vjsproj", ".xproj", ".sln")
    ACC_MAX_YEARS: int = 5

    def __init__(self, root: str, proj_dir: str, projectfiles: List[str], years: List[str]):
        self.root: str = normalize_rel(root)
        self.dir: str = normalize_rel(proj_dir)
        self.rel_dir: str = normalize_rel(os.path.relpath(proj_dir, root))
        vprint(f"  {self.rel_dir}")

        self.projectfiles: List[str] = projectfiles

        self.total_modifications: int = 0
        self.modification_dates: List[str] = []
        self.year_counts: Dict[str, int] = {year: 0 for year in years}

        self.acc_len: int = min(Project.ACC_MAX_YEARS, len(years))
        self.accumulators: Dict[str, int] = {f"Acc_{i}": 0 for i in range(1, self.acc_len + 1)}

    def __lt__(self, other):
        for i in range(self.acc_len, 0, -1):
            acc_self = self.accumulators.get(f"Acc_{i}", 0)
            acc_other = other.accumulators.get(f"Acc_{i}", 0)
            if acc_self != acc_other:
                return acc_self > acc_other
        return self.rel_dir < other.rel_dir

    def _get_git_modification_dates(self) -> List[str]:
        """
        Generate a list of dates for commits that modified files under the given directory only.
        Uses: git -C <directory> log --pretty=format:%ad --date=short -- .
        On failure, prints a warning and returns an empty list.
        """
        try:
            result = subprocess_check(["git", "-C", self.dir, "log", "--pretty=format:%ad", "--date=short", "--", "."])
            if result.returncode != 0:
                print(f"Warning: git log failed for '{self.dir}': {result.stderr.strip()}", file=sys.stderr)

            modification_dates = [date for date in result.stdout.splitlines() if date]
            self.total_modifications = len(modification_dates)

            return modification_dates

        except (subprocess.SubprocessError, OSError) as exc:
            print(f"Warning: git log exception for '{self.dir}': {exc}", file=sys.stderr)
            return []

    def _tally_year_counts(self, modification_dates: List[str]) -> None:
        """Count commits per target year from a list of commit years."""
        modification_years = [date.split("-")[0] for date in modification_dates]
        for y in modification_years:
            if y in self.year_counts:
                self.year_counts[y] += 1

    def _compute_accumulators(self) -> None:
        """Compute cumulative sums for the most recent 1..max_k years based on the provided years order."""
        vals = [self.year_counts[y] for y in self.year_counts]
        running = 0
        for k in range(1, self.acc_len + 1):
            running += vals[k - 1]
            self.accumulators[f"Acc_{k}"] = running

    def _write_csv_rows(self, out_path: str, headers: List[str], data: List[dict]) -> None:
        with open(out_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writerows(data)

    def analyze_directory(self) -> None:
        """Analyze a single project directory and return the CSV row dict."""
        modification_dates = self._get_git_modification_dates()
        self._tally_year_counts(modification_dates)
        self._compute_accumulators()
        nprint(f"    -> commits(all-time): {self.total_modifications}; in-range: {sum(self.year_counts.values())}; in last {self.acc_len} years: {sum(self.accumulators.values())}")

    def generate_csv_data(self) -> Tuple[List[dict], List[str]]:
        """Generate CSV row data for each project file in the directory."""
        rows: List[dict] = []
        for file in self.projectfiles:
            row: dict = {
                "Project": normalize_rel(os.path.join(self.rel_dir, file)),
                "Extension": os.path.splitext(file)[1],
                "Total": self.total_modifications,
            }
            row.update(self.year_counts)
            row.update(self.accumulators)
            rows.append(row)
        return rows, list(rows[0].keys()) if rows else ([], [])

    def write_csv(self, out_path: str, csv_headers: List[str]) -> Tuple[int, int]:
        rows, headers = self.generate_csv_data()
        if not rows:
            print(f"No data available for directory at '{self.rel_dir}'.", file=sys.stderr)
            return 0, 0
        if headers != csv_headers:
            print(f"Error: CSV headers mismatch for directory at '{self.rel_dir}'.", file=sys.stderr)
            print(f"Global CSV headers: {csv_headers}", file=sys.stderr)
            print(f"Local CSV headers: {headers}", file=sys.stderr)
            return 0, 0

        try:
            self._write_csv_rows(out_path, headers, rows)
        except (OSError, csv.Error, UnicodeError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 0, 0

        return len(rows), len(headers)
