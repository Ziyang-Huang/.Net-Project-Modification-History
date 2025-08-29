import csv
import fnmatch
import os
import re
import subprocess
import sys
from typing import List, Set, Tuple

from project import Project
from tools import normalize_rel, nprint, subprocess_check, vprint


class ProjectModificationAnalyzer:
    def __init__(self, root: str, years: List[str], selected_exts: Tuple[str, ...], ignore_patterns: List[str]) -> None:
        self.root: str = root
        self.years: List[str] = years
        self.selected_exts: Tuple[str, ...] = selected_exts
        self.ignore_patterns: List[str] = ignore_patterns
        self.projects: List[Project] = []
        self.filtered: List[Project] = []
        self.ignored: List[Project] = []

    def _hello(self) -> None:
        nprint("Starting analysis")
        nprint(f"    Root: {self.root}")
        nprint(f"    Time Range: past [{len(self.years)}] years")
        nprint(f"    Project Types: {', '.join(self.selected_exts)}")
        nprint(f"    Ignore Patterns: {', '.join(self.ignore_patterns) if self.ignore_patterns else '(none)'}")

    def _find_extensions(self, filenames: List[str]) -> Set[str]:
        exts = set()
        for filename in filenames:
            _, ext = os.path.splitext(filename.lower())
            if ext in self.selected_exts:
                exts.add(ext)
        return exts

    def _find_projects(self) -> List[Project]:
        projects = []
        for dirpath, _, filenames in os.walk(self.root):
            exts = self._find_extensions(filenames)
            if exts:
                projects.append(Project(self.root, dirpath, exts, self.years))
        return sorted(projects)

    def _is_ignored(self, project: Project) -> bool:
        if not self.ignore_patterns:
            return False

        for pattern in self.ignore_patterns:
            # glob match or directory prefix match
            if fnmatch.fnmatchcase(project.rel_dir, pattern):
                return True
            if project.rel_dir == pattern or project.rel_dir.startswith(pattern + "/"):
                return True
        return False

    def _filter_projects(self) -> Tuple[List[Project], List[Project]]:
        filtered: List[Project] = []
        ignored: List[Project] = []
        for proj in self.projects:
            if self._is_ignored(proj):
                ignored.append(proj)
            else:
                filtered.append(proj)
        return filtered, ignored

    def _aggregate_modifications(self) -> List[dict]:
        data: List[dict] = []
        total_dirs = len(self.filtered)
        for idx, project in enumerate(self.filtered, start=1):
            nprint(f"[{idx}/{total_dirs}] Analyzing: {project.rel_dir}")
            row = project.analyze_directory()
            data.append(row)
        return data

    def _sanitize_branch_name(self, name: str) -> str:
        # Replace path separators and spaces; allow alnum, dot, underscore, dash
        safe = name.replace(os.sep, "-").replace("/", "-")
        safe = re.sub(r"[^A-Za-z0-9._-]", "-", safe)
        return safe or "unknown"

    def _get_repo_branch_and_head(self) -> Tuple[str, str]:
        """Return (branch, short_sha6) for the repo at root_dir. On failure, ('unknown','unknown')."""
        try:
            # Prefer branch --show-current; fallback to rev-parse
            r1 = subprocess_check(["git", "-C", self.root, "branch", "--show-current"])
            branch = r1.stdout.strip()
            if not branch:
                r2 = subprocess_check(["git", "-C", self.root, "rev-parse", "--abbrev-ref", "HEAD"])
                if r2.returncode == 0:
                    branch = r2.stdout.strip()
            if branch.upper() == "HEAD" or not branch:
                branch = "detached"

            r3 = subprocess_check(["git", "-C", self.root, "rev-parse", "--short=6", "HEAD"])
            if r3.returncode != 0:
                print(f"Warning: git rev-parse failed at '{self.root}': {r3.stderr.strip()}", file=sys.stderr)
                return ("unknown", "unknown")
            sha = r3.stdout.strip()
            return (self._sanitize_branch_name(branch), sha)

        except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
            print(f"Warning: git query exception at '{self.root}': {exc}", file=sys.stderr)
            return ("unknown", "unknown")

    def _build_filename_suffix(self) -> str:
        sel_norm = sorted(self.selected_exts or ())
        all_norm = sorted(Project.ALLOWED_TYPES)
        if sel_norm and sel_norm != all_norm:
            tokens = [e.lstrip(".") for e in sel_norm]
            return "_" + "_".join(tokens)
        return ""

    def _determine_output_path(self, output_dir: str) -> str:
        branch, sha = self._get_repo_branch_and_head()
        repo_name = os.path.basename(os.path.normpath(self.root)) or "repo"
        repo_safe = self._sanitize_branch_name(repo_name)
        suffix = self._build_filename_suffix()
        filename = f"{repo_safe}_{branch}_{sha}{suffix}.csv"
        os.makedirs(output_dir, exist_ok=True)
        return os.path.join(output_dir, filename)

    def _build_headers(self, years: List[str], acc_max: int = Project.ACC_MAX_YEARS) -> List[str]:
        return ["Directory", "ProjectType", "Total"] + years + [f"Acc_{i}" for i in range(1, acc_max + 1)]

    def _write_csv_rows(self, out_path: str, headers: List[str], data: List[dict]) -> None:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in data:
                writer.writerow(row)

    def _write_csv(self, data: List[dict], output_dir: str) -> None:
        out_path = self._determine_output_path(output_dir)
        headers = self._build_headers(self.years, min(Project.ACC_MAX_YEARS, len(self.years)))
        self._write_csv_rows(out_path, headers, data)
        print(f"CSV created: '{out_path}'")
        print(f"    rows: {len(data)}")
        print(f"    columns: {len(headers)}")

    def analyze(self, output_dir: str) -> None:
        self._hello()

        self.projects = self._find_projects()
        nprint(f"Found {len(self.projects)} project directories before filtering")

        self.filtered, self.ignored = self._filter_projects()
        if not self.filtered:
            print("No project directories (.bproj/.csproj/.vcxproj/.xproj/.sln) found. Exiting...")
            return

        if self.ignored:
            nprint(f"    Ignored {len(self.ignored)} directories via patterns: {', '.join(self.ignore_patterns)}")
            vprint("  -> " + " | ".join(sorted(normalize_rel(p.rel_dir) for p in self.ignored)))

        nprint(f"Using {len(self.filtered)} project directories after filtering\n")
        data = self._aggregate_modifications()
        self._write_csv(data, output_dir)
