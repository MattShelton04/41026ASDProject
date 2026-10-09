"""Exercise the nginx entrypoint's hosts-file handling without Docker or DNS."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHELL = shutil.which("sh")


@pytest.mark.skipif(SHELL is None, reason="POSIX shell required; exercised on Linux CI")
@pytest.mark.parametrize(
    ("host", "hosts", "expected"),
    [
        ("host.docker.internal", "172.17.0.1 host.docker.internal\n", "172.17.0.1"),
        ("host.docker.internal", "172.17.0.1 gateway host.docker.internal\n", "172.17.0.1"),
        ("shared-ai-mode", "172.17.0.1 host.docker.internal\n", "shared-ai-mode"),
        (
            "host.docker.internal",
            "# 192.0.2.1 host.docker.internal\n"
            "192.0.2.2 host.docker.internal.example # host.docker.internal\n",
            "host.docker.internal",
        ),
        ("ai-host", "fd00::1 ai-host\n", "[fd00::1]"),
        ("192.0.2.5", "127.0.0.1 localhost\n", "192.0.2.5"),
    ],
)
def test_ai_proxy_host_resolution(tmp_path: Path, host: str, hosts: str, expected: str) -> None:
    hosts_path = tmp_path / "hosts"
    hosts_path.write_text(hosts, encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - fixed sh argv, no shell
        [
            SHELL or "sh",
            "-c",
            '. "$1"; propertyscope_resolve_ai_host "$2" "$3"',
            "proxy-host-test",
            str(ROOT / "deployment/nginx/19-ai-mode-host.envsh"),
            host,
            str(hosts_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == expected


def test_ai_proxy_hook_runs_before_template_substitution() -> None:
    dockerfile = (ROOT / "shared/frontend/Dockerfile").read_text(encoding="utf-8")
    assert (
        "COPY --chmod=755 deployment/nginx/19-ai-mode-host.envsh "
        "/docker-entrypoint.d/19-ai-mode-host.envsh"
    ) in dockerfile
    assert 'NGINX_ENVSUBST_FILTER="AI_MODE_(HOST|PORT|SERVICE_TOKEN)"' in dockerfile
