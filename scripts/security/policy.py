"""Reviewed inputs for the security scans: slice ownership, exceptions and scan settings."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASELINE_NAME = ".secrets.baseline"
ACCEPTED_RISKS_PATH = Path(__file__).resolve().parent / "accepted-risks.toml"
EVIDENCE_DIRECTORY = REPOSITORY_ROOT / "docs" / "release-2" / "evidence" / "security"
REPORT_NAME = "pre-commit-report.md"

# detect-secrets settings, recorded in `.secrets.baseline` so the hook uses the same ones.
# Paths can arrive with either separator on Windows, hence `[\\/]`.
DETECT_SECRETS_EXCLUDE_FILES = (
    # Generated lockfile and the baseline itself (it stores hashed secrets).
    r"(^|[\\/])(uv\.lock|\.secrets\.baseline)$",
    # Third-party vendored browser code.
    r"(^|[\\/])vendor[\\/]",
    # Binary assets that cannot hold reviewable text.
    r"\.(png|jpe?g|gif|webp|ico|pdf|zip|gz|woff2?|ttf|parquet|sqlite3?|db)$",
)
DETECT_SECRETS_EXCLUDE_LINES = (
    # A 40-128 hex digest assigned to a key or constant named as a digest or commit
    # (content_hash, sha256, corpus_version, BASELINE, commit, ...). Evidence files and tests pin
    # these on purpose.
    r"(?i)\w*(sha|hash|digest|checksum|fingerprint|corpus_version|baseline|commit)\w*"
    r"[\"']?\s*[:=]\s*\(?\s*[\"']?[0-9a-f]{40,128}\b",
)

# Release 2 slice ownership. The Shared platform is led by the Student 1 owner.
SHARED_LEAD_STUDENT = 1
STUDENT_PREFIX = re.compile(r"^student-(?P<number>[1-9])/")
TEAM_ROW = re.compile(
    r"^\|\s*(?P<number>[1-9])\s*\|\s*(?P<owner>[^|/]+?)\s*/\s*\d+\s*\|\s*\[(?P<feature>[^\]]+)\]",
    re.MULTILINE,
)


class PolicyError(ValueError):
    """A reviewed security input is missing or malformed."""


@dataclass(frozen=True)
class Slice:
    """One owned area of the repository."""

    key: str
    title: str
    owner: str
    feature: str


@dataclass(frozen=True)
class AcceptedVulnerability:
    """A reviewed pip-audit exception."""

    package: str
    ids: tuple[str, ...]
    reason: str
    follow_up: str
    reviewed: str


@dataclass(frozen=True)
class RuffFix:
    """A Ruff security finding fixed in code when the rules were adopted."""

    path: str
    rule: str
    count: int
    change: str


@dataclass(frozen=True)
class AcceptedRisks:
    """The reviewed exceptions register."""

    vulnerabilities: tuple[AcceptedVulnerability, ...]
    ruff_fixed: tuple[RuffFix, ...]

    def ignored_vulnerability_ids(self) -> tuple[str, ...]:
        return tuple(sorted({vuln for item in self.vulnerabilities for vuln in item.ids}))

    def vulnerability(self, package: str, vuln_id: str) -> AcceptedVulnerability | None:
        for item in self.vulnerabilities:
            if item.package == package.lower() and vuln_id in item.ids:
                return item
        return None


def _text(entry: dict[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PolicyError(f"{where}: `{key}` must be a non-empty string")
    return " ".join(value.split())


def load_accepted_risks(path: Path = ACCEPTED_RISKS_PATH) -> AcceptedRisks:
    """Load and validate the reviewed exceptions register."""
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PolicyError(f"cannot read {path.name}: {exc}") from exc
    vulnerabilities: list[AcceptedVulnerability] = []
    for index, entry in enumerate(document.get("pip_audit", [])):
        where = f"pip_audit[{index}]"
        ids = entry.get("ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            raise PolicyError(f"{where}: `ids` must be a non-empty list of strings")
        vulnerabilities.append(
            AcceptedVulnerability(
                package=_text(entry, "package", where).lower(),
                ids=tuple(ids),
                reason=_text(entry, "reason", where),
                follow_up=_text(entry, "follow_up", where),
                reviewed=_text(entry, "reviewed", where),
            )
        )
    fixes: list[RuffFix] = []
    for index, entry in enumerate(document.get("ruff_fixed", [])):
        where = f"ruff_fixed[{index}]"
        count = entry.get("count")
        if not isinstance(count, int) or count < 1:
            raise PolicyError(f"{where}: `count` must be a positive integer")
        fixes.append(
            RuffFix(
                path=_text(entry, "path", where),
                rule=_text(entry, "rule", where),
                count=count,
                change=_text(entry, "change", where),
            )
        )
    return AcceptedRisks(tuple(vulnerabilities), tuple(fixes))


def load_slices(readme: str) -> dict[str, Slice]:
    """Build Shared plus student-N slices from the README team table."""
    students: dict[str, Slice] = {}
    for match in TEAM_ROW.finditer(readme):
        number = match["number"]
        students[f"student-{number}"] = Slice(
            key=f"student-{number}",
            title=f"Student {number}",
            owner=match["owner"].strip(),
            feature=match["feature"].strip(),
        )
    if not students:
        raise PolicyError("README.md has no recognisable team table")
    lead = students.get(f"student-{SHARED_LEAD_STUDENT}")
    shared = Slice(
        key="shared",
        title="Shared platform",
        owner=f"{lead.owner} (group lead)" if lead else "Group lead",
        feature="Edge, contracts, AI services, scripts, CI and documentation",
    )
    return {"shared": shared, **dict(sorted(students.items()))}


def slice_key(path: str) -> str:
    """Return the owning slice key for a repository-relative POSIX path."""
    match = STUDENT_PREFIX.match(path)
    return f"student-{match['number']}" if match else "shared"


def to_posix(path: str) -> str:
    """Normalise a tool-reported relative path to forward slashes."""
    return PurePosixPath(path.replace("\\", "/")).as_posix()


@dataclass(frozen=True)
class RuffPolicy:
    """The Ruff exception tables that apply to the `S` rules."""

    per_file_ignores: dict[str, tuple[str, ...]]
    owner_exceptions: dict[str, tuple[str, ...]]
    extend_exclude: tuple[str, ...]
    target_version: str

    def owner_exception(self, path: str, code: str) -> bool:
        return any(
            fnmatchcase(path, pattern) and _covers(codes, code)
            for pattern, codes in self.owner_exceptions.items()
        )

    def isolated_arguments(self) -> tuple[str, ...]:
        """`ruff --isolated` arguments that keep the reviewed policy but not owner exceptions."""
        # JSON strings and arrays are valid TOML values for these ASCII patterns and codes.
        ignores = ", ".join(
            f"{json.dumps(pattern)} = {json.dumps(list(codes))}"
            for pattern, codes in sorted(self.per_file_ignores.items())
        )
        return (
            "--isolated",
            "--config",
            f"target-version = {json.dumps(self.target_version)}",
            "--config",
            f"extend-exclude = {json.dumps(list(self.extend_exclude))}",
            "--config",
            f"lint.per-file-ignores = {{ {ignores} }}",
        )


def _covers(codes: tuple[str, ...], code: str) -> bool:
    return any(code.startswith(prefix) for prefix in codes)


def load_ruff_policy(pyproject: str) -> RuffPolicy:
    """Read the Ruff exception tables from the root `pyproject.toml` text."""
    ruff = tomllib.loads(pyproject).get("tool", {}).get("ruff", {})
    lint = ruff.get("lint", {})
    if "S" not in lint.get("select", []):
        raise PolicyError("[tool.ruff.lint] select must include the S (flake8-bandit) rules")

    def table(name: str) -> dict[str, tuple[str, ...]]:
        raw = lint.get(name, {})
        return {str(key): tuple(str(code) for code in value) for key, value in raw.items()}

    return RuffPolicy(
        per_file_ignores=table("per-file-ignores"),
        owner_exceptions=table("extend-per-file-ignores"),
        extend_exclude=tuple(str(item) for item in ruff.get("extend-exclude", [])),
        target_version=str(ruff.get("target-version", "py312")),
    )
