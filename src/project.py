import os
import subprocess
import sys
from typing import Dict, List, Set, Tuple

from tools import normalize_rel, nprint, subprocess_check


class Project:
    # Supported project types and accumulator configuration
    ALLOWED_TYPES: Tuple[str, ...] = (".bproj", ".csproj", ".vcxproj", ".xproj", ".sln")
    ACC_MAX_YEARS: int = 5

    def __init__(self, root: str, proj_dir: str, exts: Set[str], years: List[str]):
        self.root: str = normalize_rel(root)
        self.dir: str = normalize_rel(proj_dir)
        self.rel_dir: str = normalize_rel(os.path.relpath(proj_dir, root))

        self.extensions: Set[str] = exts

        self.total_modifications: int = 0
        self.modification_dates: List[str] = []
        self.year_counts: Dict[str, int] = {year: 0 for year in years}

        self.acc_len: int = min(Project.ACC_MAX_YEARS, len(years))
        self.accumulators: Dict[str, int] = {f"Acc_{i}": 0 for i in range(1, self.acc_len + 1)}

    def __lt__(self, other):
        return self.dir < other.dir

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

    def analyze_directory(self) -> Dict[str, int]:
        """Analyze a single project directory and return the CSV row dict."""
        modification_dates = self._get_git_modification_dates()
        self._tally_year_counts(modification_dates)
        self._compute_accumulators()
        row: Dict[str, int] = {  # type: ignore[assignment]
            "Directory": self.rel_dir,
            "ProjectType": ", ".join(sorted(self.extensions)),
            "Total": self.total_modifications,
        }
        row.update(self.year_counts)
        row.update(self.accumulators)
        nprint(f"    -> commits(all-time): {self.total_modifications}; in-range: {sum(self.year_counts.values())}")
        return row
