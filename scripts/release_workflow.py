#!/usr/bin/env python3
"""Latest-version and stable-release validation / scaffolding for this repo.

Subcommands:
  version-check     Validate that VERSION, docs/changelog/vX.Y.Z.md,
                    docs/CHANGELOG.md, and the README badge are coherent.
  release-prepare   Scaffold a stable release file and CHANGELOG row.
  release           Validate the release bundle and create the stable
                    promotion commit plus the vX.Y.Z tag.
  commit-msg-check  Validate a commit message file against the standard
                    (used by tools/git-hooks/commit-msg).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"
README_FILE = REPO_ROOT / "README.md"
CHANGELOG_INDEX = REPO_ROOT / "docs" / "CHANGELOG.md"
CHANGELOG_DIR = REPO_ROOT / "docs" / "changelog"
RELEASES_DIR = CHANGELOG_DIR / "releases"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
VERSION_SUFFIX_RE = re.compile(r"^(.*) \(v(\d+\.\d+\.\d+)\)$")
RELEASE_SUBJECT_RE = re.compile(r"^release: promote v(\d+\.\d+\.\d+) to stable$")
WIP_SUBJECT_RE = re.compile(r"^WIP: \S")
SUPPORT_SUBJECT_RE = re.compile(r"^(docs|test|chore): \S")
BADGE_RE = re.compile(r"!\[Version\]\(([^)]+)\)")
BOLD_SUMMARY_RE = re.compile(r"^\*\*(.+)\*\*$", re.MULTILINE)


def fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(1)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def read_version() -> str:
    if not VERSION_FILE.exists():
        fail("version-check: VERSION file is missing")
    version = read_text(VERSION_FILE).strip()
    if not SEMVER_RE.match(version):
        fail(f"version-check: VERSION '{version}' is not full semver")
    return version


def today_iso() -> str:
    return _dt.date.today().isoformat()


def version_file_path(version: str) -> Path:
    return CHANGELOG_DIR / f"v{version}.md"


def version_link(version: str) -> str:
    return f"[v{version}](changelog/v{version}.md)"


def release_file_name(version: str, slug: str) -> str:
    return f"v{version}-{slug}.md"


def release_file_path(version: str, slug: str) -> Path:
    return RELEASES_DIR / release_file_name(version, slug)


def release_file_relative(version: str, slug: str) -> str:
    return f"changelog/releases/{release_file_name(version, slug)}"


def rel_to_repo(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def parse_changelog_rows() -> list[tuple[str, list[str]]]:
    """Return [(raw_line, [col1, col2, col3])] for every data row in the table."""
    rows: list[tuple[str, list[str]]] = []
    for raw in read_text(CHANGELOG_INDEX).splitlines():
        if not raw.startswith("|"):
            continue
        if re.match(r"^\|[- ]+\|", raw):
            continue
        cols = [part.strip() for part in raw.split("|")[1:-1]]
        rows.append((raw, cols))
    return rows


def extract_summary(version_file: Path) -> str:
    body = read_text(version_file)
    match = BOLD_SUMMARY_RE.search(body)
    if not match:
        fail(
            f"version-check: {rel_to_repo(version_file)} has no top-line "
            "'**Summary**' bold line"
        )
    summary = match.group(1).strip()
    if not summary:
        fail(f"version-check: {rel_to_repo(version_file)} has an empty Summary")
    if summary.endswith("."):
        fail(f"version-check: {rel_to_repo(version_file)} Summary must not end with a period")
    if VERSION_SUFFIX_RE.match(summary):
        fail(f"version-check: {rel_to_repo(version_file)} Summary must not include a version suffix")
    return summary


def ensure_readme_badge(version: str) -> None:
    body = read_text(README_FILE)
    match = BADGE_RE.search(body)
    if not match:
        fail("version-check: README.md is missing the Version badge")
    badge_url = match.group(1)
    if version not in badge_url:
        fail(f"version-check: README.md Version badge does not include VERSION '{version}'")


def find_version_rows(version: str, summary: str) -> list[tuple[str, list[str]]]:
    target_link = version_link(version)
    return [row for row in parse_changelog_rows() if row[1][0] == target_link and row[1][2] == summary]


def find_release_rows(version: str, release_label: str) -> list[tuple[str, list[str]]]:
    target_link = version_link(version)
    return [row for row in parse_changelog_rows() if row[1][0] == target_link and row[1][2] == release_label]


def check_version_bundle() -> tuple[str, str, Path]:
    version = read_version()
    version_file = version_file_path(version)
    if not version_file.exists():
        fail(f"version-check: expected {rel_to_repo(version_file)}")
    summary = extract_summary(version_file)
    rows = find_version_rows(version, summary)
    if len(rows) != 1:
        fail(
            f"version-check: docs/CHANGELOG.md must contain exactly one version row "
            f"for v{version} with the canonical Summary"
        )
    ensure_readme_badge(version)
    return version, summary, version_file


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def current_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def ensure_main_branch(context: str) -> None:
    branch = current_branch()
    if branch != "main":
        fail(f"{context}: expected current branch to be main; got '{branch or '(detached)'}'")


def release_files_for_version(version: str) -> list[Path]:
    if not RELEASES_DIR.exists():
        return []
    return sorted(
        p
        for p in RELEASES_DIR.iterdir()
        if p.name.startswith(f"v{version}-") and p.suffix == ".md"
    )


def parse_release_title(release_file: Path, version: str) -> str:
    body = read_text(release_file)
    pattern = rf"^# (.+) \(v{re.escape(version)}\)$"
    match = re.search(pattern, body, re.MULTILINE)
    if not match:
        fail(
            f"release: {rel_to_repo(release_file)} must start with "
            f"'# <Title> (v{version})'"
        )
    return match.group(1).strip()


def ensure_no_todo(release_file: Path) -> None:
    body = read_text(release_file)
    if re.search(r"\bTODO\b", body):
        fail(f"release: {rel_to_repo(release_file)} still contains TODO placeholders")


def release_label(title: str, release_file: Path) -> str:
    return f"Release: [{title}](changelog/releases/{release_file.name})"


def check_release_bundle() -> tuple[str, Path, str, str]:
    version, _summary, _version_file = check_version_bundle()
    release_files = release_files_for_version(version)
    if len(release_files) != 1:
        fail(
            f"release: expected exactly one release file under "
            f"docs/changelog/releases/ for v{version}"
        )
    release_file = release_files[0]
    title = parse_release_title(release_file, version)
    ensure_no_todo(release_file)
    label = release_label(title, release_file)
    rows = find_release_rows(version, label)
    if len(rows) != 1:
        fail(
            f"release: docs/CHANGELOG.md must contain exactly one stable release "
            f"row for v{version} using '{label}'"
        )
    return version, release_file, title, label


def insert_release_row(release_row: str) -> None:
    lines = read_text(CHANGELOG_INDEX).splitlines()
    separator_index = next(
        (i for i, line in enumerate(lines) if line.strip() == "|---|---|---|"),
        -1,
    )
    if separator_index == -1:
        fail("release-prepare: docs/CHANGELOG.md is missing the changelog table header")
    lines.insert(separator_index + 1, release_row)
    body = "\n".join(lines).rstrip("\n") + "\n"
    write_text(CHANGELOG_INDEX, body)


def release_prepare(args: argparse.Namespace) -> None:
    ensure_main_branch("release-prepare")
    version, _summary, _version_file = check_version_bundle()
    title = args.title.strip()
    slug = slugify(args.slug)
    if not title:
        fail("release-prepare: release title must not be empty")
    if not slug:
        fail("release-prepare: slug must contain at least one letter or number")

    existing = release_files_for_version(version)
    if existing:
        fail(
            f"release-prepare: a release file already exists for v{version}; "
            "edit it directly or finish the release"
        )

    target_file = release_file_path(version, slug)
    target_relative = rel_to_repo(target_file)
    current_date = today_iso()
    release_row = (
        f"| {version_link(version)} | {current_date} | "
        f"Release: [{title}]({release_file_relative(version, slug)}) |"
    )

    duplicate = find_release_rows(version, f"Release: [{title}]({release_file_relative(version, slug)})")
    if duplicate:
        fail(f"release-prepare: docs/CHANGELOG.md already contains a stable release row for v{version}")

    body = (
        f"# {title} (v{version})\n"
        f"\n"
        f"Shipped: {current_date}\n"
        f"\n"
        f"Stable promotion record for [v{version}](../v{version}.md).\n"
        f"\n"
        f"## Overview\n"
        f"\n"
        f"TODO\n"
        f"\n"
        f"## Highlights\n"
        f"\n"
        f"- TODO\n"
        f"\n"
        f"## Stable Validation\n"
        f"\n"
        f"- TODO\n"
        f"\n"
        f"## Version\n"
        f"\n"
        f"- Experimental version: [v{version}](../v{version}.md)\n"
    )
    write_text(target_file, body)
    insert_release_row(release_row)

    print(f"Created {target_relative}")
    print("Updated docs/CHANGELOG.md with the stable release row stub")


def unique_dirty_paths() -> list[str]:
    paths: set[str] = set()
    for args in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        result = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            fail(f"release: '{' '.join(args)}' failed: {result.stderr.strip() or result.stdout.strip()}")
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                paths.add(line)
    return sorted(paths)


def ensure_only_release_files_dirty(release_file: Path) -> None:
    allowed = {
        rel_to_repo(CHANGELOG_INDEX),
        rel_to_repo(release_file),
        ".canary--pre-commit",
    }
    dirty = unique_dirty_paths()
    disallowed = [p for p in dirty if p not in allowed]
    if disallowed:
        fail(
            "release: only release artefacts and the transient "
            ".canary--pre-commit receipt may be dirty; found "
            + ", ".join(disallowed)
        )
    if not dirty:
        fail("release: no release artefact changes are present to commit")


def git_run(args: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=capture,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or (result.stdout or "").strip()
        fail(f"git {' '.join(args[1:])} failed: {detail}")
    return (result.stdout or "").strip()


def release_finalize(_args: argparse.Namespace) -> None:
    ensure_main_branch("release")
    version, release_file, _title, _label = check_release_bundle()
    ensure_only_release_files_dirty(release_file)

    existing_tag = git_run(["git", "tag", "--list", f"v{version}"], capture=True)
    if existing_tag:
        fail(f"release: tag v{version} already exists")

    git_run(["git", "add", "--", rel_to_repo(CHANGELOG_INDEX), rel_to_repo(release_file)])
    git_run(["git", "commit", "-m", f"release: promote v{version} to stable"])
    git_run(["git", "tag", "-a", f"v{version}", "-m", f"Release v{version}"])


def version_check(_args: argparse.Namespace) -> None:
    version, _summary, _version_file = check_version_bundle()
    print(f"version-check: v{version} bundle is coherent")


def commit_msg_check(args: argparse.Namespace) -> None:
    msg_path = Path(args.message_file)
    if not msg_path.is_file():
        fail(f"commit-msg-check: '{msg_path}' is not a file")
    branch = args.branch or current_branch()

    subject = ""
    for raw in read_text(msg_path).splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        subject = line
        break

    if not subject:
        fail("commit-msg: empty commit subject")

    if SUPPORT_SUBJECT_RE.match(subject):
        return

    if WIP_SUBJECT_RE.match(subject):
        if branch == "main":
            fail("commit-msg: WIP commits are not allowed on main")
        return

    release_match = RELEASE_SUBJECT_RE.match(subject)
    if release_match:
        if branch != "main":
            fail("commit-msg: release commits are only allowed on main")
        version = release_match.group(1)
        actual = read_version()
        if version != actual:
            fail(f"commit-msg: VERSION is '{actual}' but release subject says v{version}")
        check_release_bundle()
        return

    versioned_match = VERSION_SUFFIX_RE.match(subject)
    if versioned_match:
        summary = versioned_match.group(1)
        version = versioned_match.group(2)
        actual = read_version()
        if version != actual:
            fail(f"commit-msg: VERSION is '{actual}' but subject says v{version}")
        _, canonical_summary, _ = check_version_bundle()
        if summary != canonical_summary:
            print("commit-msg: subject Summary does not match the canonical "
                  f"docs/changelog/v{version}.md Summary", file=sys.stderr)
            print(f"  subject:   {summary}", file=sys.stderr)
            print(f"  canonical: {canonical_summary}", file=sys.stderr)
            sys.exit(1)
        return

    if branch == "main":
        fail("commit-msg: non-support commits on main must be versioned or use "
             "'release: promote vX.Y.Z to stable'")
    fail("commit-msg: non-support branch commits must use 'WIP: ' or a versioned "
         "'<Summary> (vX.Y.Z)' subject")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub_version = sub.add_parser("version-check", help="Validate the version bundle")
    sub_version.set_defaults(func=version_check)

    sub_prepare = sub.add_parser("release-prepare", help="Scaffold a stable release")
    sub_prepare.add_argument("--title", required=True, help="Stable release title")
    sub_prepare.add_argument("--slug", required=True, help="Release slug for the filename")
    sub_prepare.set_defaults(func=release_prepare)

    sub_release = sub.add_parser("release", help="Create the stable promotion commit and tag")
    sub_release.set_defaults(func=release_finalize)

    sub_commit = sub.add_parser(
        "commit-msg-check",
        help="Validate a commit message file (used by tools/git-hooks/commit-msg)",
    )
    sub_commit.add_argument("message_file")
    sub_commit.add_argument(
        "branch",
        nargs="?",
        default="",
        help="Optional branch override; defaults to the current branch",
    )
    sub_commit.set_defaults(func=commit_msg_check)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
