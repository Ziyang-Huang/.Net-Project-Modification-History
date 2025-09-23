import csv
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import List, Set, Tuple

from project import Project
from tools import normalize_rel, nprint, subprocess_check, vprint


class ProjectModificationAnalyzer:
    def __init__(self, root: str, years: List[str], selected_exts: Tuple[str, ...], ignore_patterns: List[str]) -> None:
        self.root: str = root
        self.years: List[str] = years
        self.csv_headers: List[str] = self._build_headers(years, Project.ACC_MAX_YEARS)
        self.selected_exts: Set[str] = set(selected_exts)
        self.ignore_patterns: List[str] = ignore_patterns
        self._ignore_regex: List[re.Pattern] = self._compile_ignore_patterns(ignore_patterns)
        nprint("Precompiling ignore patterns...")
        for pattern, cregex in zip(self.ignore_patterns, self._ignore_regex):
            nprint(f"  {pattern} -> {cregex.pattern}")
        self.projects: List[Project] = []
        self.filtered: List[Project] = []
        self.ignored: List[Project] = []

    def _build_headers(self, years: List[str], acc_max: int = Project.ACC_MAX_YEARS) -> List[str]:
        return ["Project", "Extension", "Total"] + years + [f"Acc_{i}" for i in range(1, acc_max + 1)]

    def _hello(self) -> None:
        nprint("\nStarting analysis")
        nprint(f"    Root: {self.root}")
        nprint(f"    Time Range: past [{len(self.years)}] years")
        nprint(f"    Project Types: {', '.join(self.selected_exts)}")
        nprint(f"    Ignore Patterns: {', '.join(self.ignore_patterns) if self.ignore_patterns else '(none)'}")
        nprint("\nSearching for project files...")

    def _find_projectfiles(self, filenames: List[str]) -> List[str]:
        projectfiles = []
        for filename in filenames:
            _, ext = os.path.splitext(filename)
            ext = ext.lower()
            if ext in self.selected_exts:
                projectfiles.append(filename)
        return sorted(projectfiles)

    def _find_projects(self) -> List[Project]:
        projects = []
        for dirpath, _, filenames in os.walk(self.root):
            projectfiles = self._find_projectfiles(filenames)
            if projectfiles:
                projects.append(Project(self.root, dirpath, projectfiles, self.years))
        return projects

    @staticmethod
    def _compile_ignore_patterns(ignore_patterns: List[str]) -> List[re.Pattern]:
        if not ignore_patterns:
            return []

        compiled: List[re.Pattern] = []
        for pattern in ignore_patterns:
            p = normalize_rel(pattern) + ("/" if pattern.endswith("/") or pattern.endswith("\\") else "")
            p = p.replace(".", "\\.").replace("**", ".*").replace("*", "[^/]*")
            compiled.append(re.compile(p))
        return compiled

    def _is_ignored(self, project: Project) -> bool:
        if not self.ignore_patterns:
            return False

        rel_dir = project.rel_dir
        if any(cregex.search(rel_dir) for cregex in self._ignore_regex):
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

        if ignored:
            nprint(f"    Ignored {len(ignored)} directories via patterns: {', '.join(self.ignore_patterns)}")
            vprint("  -> " + "\n  -> ".join(sorted(normalize_rel(p.rel_dir) for p in ignored)))

        return filtered, ignored

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
        all_norm = sorted(Project.SUPPORTED_TYPES)
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

    def _write_csv_headers(self, out_path: str, headers: List[str]) -> None:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()

    def _add_timestamp(self, filename: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name, ext = os.path.splitext(filename)
        return f"{name}_{timestamp}{ext}"

    def _prepare_csv(self, output_dir: str) -> str:
        out_path = self._determine_output_path(output_dir)
        try:
            self._write_csv_headers(out_path, self.csv_headers)
        except PermissionError:
            print(f"PermissionError: Unable to write to '{out_path}'. Trying a new filename with timestamp...")
            try:
                out_path = self._add_timestamp(out_path)
                self._write_csv_headers(out_path, self.csv_headers)
            except (OSError, csv.Error, UnicodeError) as e:
                print(f"Error: {e}", file=sys.stderr)
                return ""
        except (OSError, csv.Error, UnicodeError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return ""
        return out_path

    def _print_csv_stats(self, path: str, row: int, col: int) -> None:
        print(f"CSV created: '{path}'")
        print(f"    rows: {row}")
        print(f"    columns: {col}")

    def _aggregate_modifications(self) -> List[dict]:
        data: List[dict] = []
        total_dirs = len(self.filtered)
        for idx, project in enumerate(self.filtered, start=1):
            nprint(f"[{idx}/{total_dirs}] Analyzing: {project.rel_dir}")
            project.analyze_directory()
            rows, headers = project.generate_csv_data()
            if not rows:
                print(f"No data available for directory at '{project.rel_dir}'.", file=sys.stderr)
            if headers != self.csv_headers:
                print(f"Error: CSV headers mismatch for directory at '{project.rel_dir}'.", file=sys.stderr)
                print(f"Global CSV headers: {self.csv_headers}", file=sys.stderr)
                print(f"Local CSV headers: {headers}", file=sys.stderr)
                continue
            data.extend(rows)
        return data

    def _analyze_then_write(self, output_dir: str) -> bool:
        nprint("Aggregating modifications before writing CSV...")
        data = self._aggregate_modifications()
        if not data:
            print("No project modification data found. Exiting...")
            return False

        out_path = self._prepare_csv(output_dir)
        if not out_path:
            print("Failed to prepare output CSV file. Exiting...", file=sys.stderr)
            return False

        nprint(f"Output CSV will be written to: {out_path}\n")

        try:
            with open(out_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.csv_headers)
                writer.writerows(data)
        except (OSError, csv.Error, UnicodeError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return False

        self._print_csv_stats(out_path, len(data), len(self.csv_headers))
        return True

    def _write_while_analyzing(self, output_dir: str) -> bool:
        nprint("Writing CSV while analyzing projects...")
        out_path = self._prepare_csv(output_dir)
        if not out_path:
            print("Failed to prepare output CSV file. Exiting...", file=sys.stderr)
            return False

        nprint(f"Output CSV will be written to: {out_path}\n")

        output_rows, output_cols = 0, 0
        for idx, project in enumerate(self.filtered, start=1):
            nprint(f"[{idx}/{len(self.filtered)}] Analyzing: {project.rel_dir}")
            project.analyze_directory()
            rows, cols = project.write_csv(out_path, self.csv_headers)
            output_rows += rows
            if output_cols == 0:
                output_cols = cols
            else:
                if cols != output_cols:
                    print(f"Warning: Inconsistent column count for project '{project.rel_dir}': {cols} vs {output_cols}", file=sys.stderr)

        self._print_csv_stats(out_path, output_rows, output_cols)

        return True

    def analyze(self, output_dir: str, write_while_analyze: bool = False) -> None:
        self._hello()

        self.projects = self._find_projects()
        nprint(f"Found {len(self.projects)} project directories before filtering")

        self.filtered, self.ignored = self._filter_projects()
        if not self.filtered:
            print(f"No project directories ({'/'.join(Project.SUPPORTED_TYPES)}) found. Exiting...")
            return

        nprint(f"Using {len(self.filtered)} project directories after filtering\n")

        # Choose one of the two strategies below:
        # 1) Analyze all projects first, then write CSV at once
        # 2) Analyze and write CSV incrementally per project

        if write_while_analyze:
            self._write_while_analyzing(output_dir)
        else:
            self._analyze_then_write(output_dir)
