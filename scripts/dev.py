"""Cross-platform Docker Compose workflow for the local integration stack."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile, ZipFile

import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.integration-test.yml",
    "docker-compose.dev.yml",
)
FULL_DATA_COMPOSE_FILE = "docker-compose.full-data.yml"
PROFILES = ("release-0", "integration-test")
APPLICATION_SERVICES = (
    "propertyscope-shared-frontend",
    "ai-mode",
    "integration-test-feature-database",
    "integration-test-feature-backend",
    "integration-test-feature-frontend",
    "propertyscope-database-api",
    "propertyscope-database-loader",
    "propertyscope-backend",
    "propertyscope-runner",
    "propertyscope-frontend",
)
BUILD_SERVICES = APPLICATION_SERVICES
FULL_DATA_PROJECT_NAME = "41026-asd-propertyscope-full-data"
PSI_YEARLY_URL = "https://www.valuergeneral.nsw.gov.au/__psi/yearly/{partition}.zip"
PSI_WEEKLY_URL = "https://www.valuergeneral.nsw.gov.au/__psi/weekly/{partition}.zip"
PSI_ARCHIVE_BYTE_LIMIT = 750_000_000


def _compose_command(*arguments: str, full_data: bool = False) -> tuple[str, ...]:
    command = ["docker", "compose"]
    if full_data:
        command.extend(("--project-name", FULL_DATA_PROJECT_NAME))
    for filename in COMPOSE_FILES:
        command.extend(("--file", filename))
    if full_data:
        command.extend(("--file", FULL_DATA_COMPOSE_FILE))
    profiles = (*PROFILES, "full-data") if full_data else PROFILES
    for profile in profiles:
        command.extend(("--profile", profile))
    command.extend(arguments)
    return tuple(command)


def _run(command: Sequence[str], *, environment: Mapping[str, str] | None = None) -> None:
    print(f"> {shlex.join(command)}", flush=True)
    subprocess.run(command, cwd=REPOSITORY_ROOT, check=True, env=environment)


def _ensure_docker() -> None:
    _run(("docker", "info", "--format", "Docker Engine {{.ServerVersion}} is ready"))


def _ensure_openai_credential() -> None:
    """Fail clearly before Compose tries to materialise its OpenAI secret."""
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise RuntimeError(
            "OPENAI_API_KEY is required for the complete stack. Set a real key for OpenAI "
            "or a non-empty local-development value for your OpenAI-compatible endpoint."
        )


def _psi_cache_years() -> tuple[int, ...]:
    root = REPOSITORY_ROOT / ".propertyscope-source-cache" / "psi"
    if not root.is_dir():
        return ()
    return tuple(
        sorted(int(path.stem) for path in root.glob("[0-9][0-9][0-9][0-9].zip") if path.is_file())
    )


def _psi_cache_weeks() -> tuple[str, ...]:
    weekly = REPOSITORY_ROOT / ".propertyscope-source-cache" / "psi" / "weekly"
    return tuple(
        sorted(
            f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:]}"
            for path in weekly.glob("*.zip")
            if (match := re.fullmatch(r"(\d{8})\.zip", path.name)) is not None
        )
    )


def _current_psi_weeks(today: date | None = None) -> tuple[date, ...]:
    resolved = today or datetime.now(UTC).date()
    cursor = date(resolved.year, 1, 1)
    cursor += timedelta(days=(7 - cursor.weekday()) % 7)
    weeks: list[date] = []
    while cursor <= resolved:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    return tuple(weeks)


def _download_psi_archive(client: httpx.Client, url: str) -> bytes:
    """Acquire one official PSI archive, including the publisher's Range-only path."""
    response = client.get(
        url, headers={"Accept": "application/zip", "User-Agent": "PropertyScope/1.0"}
    )
    if response.status_code != 403:
        response.raise_for_status()
        if len(response.content) > PSI_ARCHIVE_BYTE_LIMIT:
            raise RuntimeError("PSI archive exceeds the 750 MB compressed safety limit")
        return response.content
    chunks: list[bytes] = []
    offset = 0
    expected_total: int | None = None
    chunk_size = 4 * 1024 * 1024
    while expected_total is None or offset < expected_total:
        end = min(offset + chunk_size - 1, PSI_ARCHIVE_BYTE_LIMIT - 1)
        ranged = client.get(
            url,
            headers={
                "Accept": "application/zip",
                "Range": f"bytes={offset}-{end}",
                "User-Agent": "PropertyScope/1.0",
            },
        )
        if ranged.status_code != 206:
            ranged.raise_for_status()
            raise RuntimeError("PSI publisher rejected bounded Range acquisition")
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", ranged.headers.get("content-range", ""))
        if match is None or int(match.group(1)) != offset:
            raise RuntimeError("PSI publisher returned an invalid content range")
        range_end, total = int(match.group(2)), int(match.group(3))
        if total > PSI_ARCHIVE_BYTE_LIMIT or len(ranged.content) != range_end - offset + 1:
            raise RuntimeError("PSI archive exceeds the compressed safety limit")
        if expected_total is not None and total != expected_total:
            raise RuntimeError("PSI archive changed during acquisition")
        expected_total = total
        chunks.append(ranged.content)
        offset = range_end + 1
    return b"".join(chunks)


def _sync_psi(*, years: Sequence[int], weeks: Sequence[date]) -> None:
    root = REPOSITORY_ROOT / ".propertyscope-source-cache" / "psi"
    targets = [
        (PSI_YEARLY_URL.format(partition=year), root / f"{year}.zip") for year in sorted(set(years))
    ]
    targets.extend(
        (
            PSI_WEEKLY_URL.format(partition=week.strftime("%Y%m%d")),
            root / "weekly" / f"{week.strftime('%Y%m%d')}.zip",
        )
        for week in sorted(set(weeks))
    )
    if not targets:
        raise RuntimeError("Select --all, --year, --week, or --current-weekly")
    with httpx.Client(timeout=None, follow_redirects=False) as client:
        for url, destination in targets:
            if destination.is_file():
                try:
                    with ZipFile(destination) as archive:
                        archive.testzip()
                    print(
                        f"PSI cache retained: {destination.relative_to(REPOSITORY_ROOT)}",
                        flush=True,
                    )
                    continue
                except BadZipFile:
                    pass
            print(f"PSI source: {url}", flush=True)
            content = _download_psi_archive(client, url)
            try:
                with ZipFile(io.BytesIO(content)) as archive:
                    if not archive.namelist() or archive.testzip() is not None:
                        raise RuntimeError("PSI publisher returned a corrupt ZIP archive")
            except BadZipFile as exc:
                raise RuntimeError("PSI publisher did not return a ZIP archive") from exc
            destination.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, destination)
            print(
                f"PSI cached: {destination.relative_to(REPOSITORY_ROOT)} "
                f"({len(content):,} bytes, sha256 {hashlib.sha256(content).hexdigest()})",
                flush=True,
            )


def _compose_environment(*, full_data: bool) -> Mapping[str, str] | None:
    if not full_data:
        return None
    years = _psi_cache_years()
    weeks = _psi_cache_weeks()
    environment = os.environ.copy()
    environment.setdefault("PROPERTYSCOPE_PSI_TRANSPORT_ENABLED", "true")
    if years:
        environment.setdefault("PROPERTYSCOPE_PSI_CACHED_YEARS", ",".join(map(str, years)))
    if weeks:
        environment.setdefault("PROPERTYSCOPE_PSI_CACHED_WEEKS", ",".join(weeks))
    return environment


def _up(*, full_data: bool) -> None:
    _ensure_openai_credential()
    _ensure_docker()
    compose_environment = _compose_environment(full_data=full_data)
    if compose_environment is not None:
        print(f"Official PSI cache: {', '.join(map(str, _psi_cache_years()))}", flush=True)
    _run(
        _compose_command(
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "180",
            *APPLICATION_SERVICES,
            full_data=full_data,
        ),
        environment=compose_environment,
    )
    print("\nIntegration console: http://localhost:5190")
    print("AI-mode health:     http://localhost:5005/health/ready")
    print("PropertyScope home: http://localhost:5100")
    print("PropertyScope:      http://localhost:5200")
    if full_data:
        print("Full-data mode:     enabled in an isolated Compose project")


def _rebuild(services: Sequence[str], *, full_data: bool) -> None:
    _ensure_openai_credential()
    _ensure_docker()
    selected = tuple(services) or APPLICATION_SERVICES
    compose_environment = _compose_environment(full_data=full_data)
    _run(
        _compose_command("build", *selected, full_data=full_data),
        environment=compose_environment,
    )
    _run(
        _compose_command(
            "up",
            "--detach",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "180",
            *selected,
            full_data=full_data,
        ),
        environment=compose_environment,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the assignment-aligned local stack with fast source reloads."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    parser.set_defaults(full_data=False)

    def add_full_data_option(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--full-data",
            action="store_true",
            help="Use the isolated, opt-in source-scale PropertyScope profile",
        )

    up = commands.add_parser("up", help="Start the complete development stack")
    add_full_data_option(up)

    rebuild = commands.add_parser(
        "rebuild",
        help="Rebuild images after dependency or Dockerfile changes",
    )
    rebuild.add_argument(
        "services",
        nargs="*",
        choices=BUILD_SERVICES,
        help="Optional application services to rebuild (all by default)",
    )
    add_full_data_option(rebuild)

    restart = commands.add_parser(
        "restart", help="Recreate application containers without rebuilding"
    )
    add_full_data_option(restart)
    down = commands.add_parser("down", help="Stop containers while preserving durable volumes")
    add_full_data_option(down)
    status = commands.add_parser("status", help="Show current service and health state")
    add_full_data_option(status)
    config_command = commands.add_parser("config", help="Validate the merged Compose configuration")
    add_full_data_option(config_command)

    logs = commands.add_parser("logs", help="Follow recent application logs")
    logs.add_argument(
        "services",
        nargs="*",
        choices=APPLICATION_SERVICES,
        help="Optional services to follow (all application services by default)",
    )
    add_full_data_option(logs)

    commands.add_parser("test", help="Run the deterministic integration-feature tests")
    commands.add_parser("check", help="Run the complete canonical quality gate")
    sync_psi = commands.add_parser(
        "sync-psi", help="Acquire official PSI annual/weekly archives into the read-only app cache"
    )
    sync_psi.add_argument(
        "--all",
        action="store_true",
        help="Acquire annual history from 1990 plus every current-year Monday archive",
    )
    sync_psi.add_argument("--year", type=int, action="append", default=[], help="Annual archive")
    sync_psi.add_argument(
        "--week", action="append", default=[], metavar="YYYY-MM-DD", help="Weekly archive"
    )
    sync_psi.add_argument(
        "--current-weekly", action="store_true", help="Acquire all Monday archives this year"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one documented development action."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "up":
            _up(full_data=arguments.full_data)
        elif arguments.command == "rebuild":
            _rebuild(arguments.services, full_data=arguments.full_data)
        elif arguments.command == "restart":
            _ensure_openai_credential()
            _ensure_docker()
            compose_environment = _compose_environment(full_data=arguments.full_data)
            _run(
                _compose_command(
                    "up",
                    "--detach",
                    "--force-recreate",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    *APPLICATION_SERVICES,
                    full_data=arguments.full_data,
                ),
                environment=compose_environment,
            )
        elif arguments.command == "down":
            _ensure_docker()
            _run(_compose_command("down", "--remove-orphans", full_data=arguments.full_data))
        elif arguments.command == "status":
            _ensure_docker()
            _run(_compose_command("ps", full_data=arguments.full_data))
        elif arguments.command == "config":
            _ensure_docker()
            _run(_compose_command("config", "--quiet", full_data=arguments.full_data))
        elif arguments.command == "logs":
            _ensure_docker()
            selected = tuple(arguments.services) or APPLICATION_SERVICES
            _run(
                _compose_command(
                    "logs",
                    "--follow",
                    "--tail",
                    "200",
                    *selected,
                    full_data=arguments.full_data,
                )
            )
        elif arguments.command == "test":
            _run(
                (
                    sys.executable,
                    "-m",
                    "pytest",
                    "examples/integration-test-feature/tests",
                    "student-1/tests",
                )
            )
        elif arguments.command == "check":
            _run((sys.executable, "scripts/check.py"))
        elif arguments.command == "sync-psi":
            current_year = datetime.now(UTC).year
            years = list(arguments.year)
            weeks: list[date] = []
            try:
                weeks.extend(date.fromisoformat(value) for value in arguments.week)
            except ValueError as exc:
                raise RuntimeError("--week must use YYYY-MM-DD") from exc
            if arguments.all:
                years.extend(range(1990, current_year))
                weeks.extend(_current_psi_weeks())
            elif arguments.current_weekly:
                weeks.extend(_current_psi_weeks())
            if any(year < 1990 or year > current_year for year in years):
                raise RuntimeError("--year must be between 1990 and the current year")
            if any(week.weekday() != 0 for week in weeks):
                raise RuntimeError("--week must be a Monday publication date")
            _sync_psi(years=years, weeks=weeks)
    except FileNotFoundError:
        print(
            "Docker or uv is not available on PATH. See README.md for prerequisites.",
            file=sys.stderr,
        )
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"Development command failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
