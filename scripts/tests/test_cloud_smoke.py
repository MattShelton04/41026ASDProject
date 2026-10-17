"""Cloud smoke test against an in-memory edge (httpx.MockTransport); no network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from scripts import cloud_smoke
from scripts.cloud_smoke import CRUD_CASES, Smoke, load_features, main
from scripts.tests.cloud_fixtures import FakeEdge, run_smoke, smoke_document

COMMIT = "0123456789abcdef0123456789abcdef01234567"  # pragma: allowlist secret
SOURCES = "/api/data-platform/v1/sources"


def _run(edge: FakeEdge, *, expect_ai: bool = False) -> list[cloud_smoke.CheckResult]:
    return run_smoke(edge, expect_ai=expect_ai).results


def test_every_enabled_feature_has_a_registered_crud_case() -> None:
    features = load_features()
    assert {feature.owner for feature in features} == {f"student-{n}" for n in range(1, 6)}
    for feature in features:
        assert feature.feature_key in CRUD_CASES
        assert CRUD_CASES[feature.feature_key]().owner == feature.owner
        assert feature.health_path == f"/api/shared-health/{feature.slug}"


def test_full_pass_creates_reads_deletes_and_leaves_nothing_behind() -> None:
    edge = FakeEdge()

    results = _run(edge)

    assert all(result.passed for result in results), [r for r in results if not r.passed]
    assert all(not items for items in edge.store.values())
    deletes = [path for method, path in edge.requests if method == "DELETE"]
    assert len(deletes) == 5
    crud = [result for result in results if result.category == "crud"]
    assert {result.owner for result in crud} == {f"student-{n}" for n in range(1, 6)}
    # Four steps per feature, plus update and confirm-update for Feature 1.
    assert len(crud) == 22
    ai = results[-1]
    assert ai.owner == "shared" and ai.detail.startswith("disabled")


def test_feature_1_case_is_full_crud_with_a_verified_update() -> None:
    edge = FakeEdge()

    results = _run(edge)

    feature_1 = [result for result in results if result.owner == "student-1"]
    crud = [result for result in feature_1 if result.category == "crud"]
    assert [result.operation for result in crud] == [
        "create",
        "read",
        "update",
        "confirm-update",
        "delete",
        "confirm-deleted",
    ]
    assert all(result.passed for result in crud)
    update = next(result for result in crud if result.operation == "update")
    assert update.method == "PUT" and update.path.startswith(f"{SOURCES}/")
    assert ("PUT", update.path) in edge.requests
    # The other features keep their create -> read -> delete -> confirm cycle.
    student_2 = [r.operation for r in results if r.owner == "student-2" and r.category == "crud"]
    assert student_2 == ["create", "read", "delete", "confirm-deleted"]


def test_feature_1_update_sends_the_full_definition_with_the_read_version() -> None:
    edge = FakeEdge()
    original = edge.__call__
    bodies: list[dict[str, object]] = []

    def spy(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            bodies.append(json.loads(request.content))
        return original(request)

    with httpx.Client(transport=httpx.MockTransport(spy)) as client:
        Smoke(client, base_url="https://edge.example").run(load_features(), expect_ai=False)

    assert len(bodies) == 1
    body = bodies[0]
    assert body["version"] == 1
    assert body["notes"] == cloud_smoke.UPDATED_NOTES
    # SourceDefinitionUpdate = SourceDefinitionCreate + version; no server-owned fields.
    assert "id" not in body
    assert {"name", "publisher", "source_url", "adapter_key", "licence_id"} <= set(body)


def test_an_update_that_does_not_persist_is_reported_and_still_cleaned_up() -> None:
    edge = FakeEdge()
    original = edge.__call__

    def ignore_put(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            # Answers like a read: the change is silently dropped.
            return original(httpx.Request("GET", request.url, headers=request.headers))
        return original(request)

    with httpx.Client(transport=httpx.MockTransport(ignore_put)) as client:
        results = Smoke(client, base_url="https://edge.example").run(
            load_features(), expect_ai=False
        )

    failed = [result for result in results if not result.passed]
    assert [(r.owner, r.operation) for r in failed] == [("student-1", "update")]
    assert "is 'Created and deleted" in failed[0].detail
    assert not edge.store[SOURCES]
    assert not any(r.operation == "confirm-update" for r in results)


def test_an_update_rejected_by_the_feature_reports_its_problem_code() -> None:
    edge = FakeEdge()
    original = edge.__call__

    def conflict(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(409, json={"code": "version_conflict"})
        return original(request)

    with httpx.Client(transport=httpx.MockTransport(conflict)) as client:
        results = Smoke(client, base_url="https://edge.example").run(
            load_features(), expect_ai=False
        )

    update = next(r for r in results if r.operation == "update")
    assert update.passed is False and "version_conflict" in update.detail
    assert not edge.store[SOURCES]


def test_an_update_without_a_read_version_is_a_failed_prerequisite() -> None:
    with pytest.raises(ValueError, match="integer version"):
        cloud_smoke._feature_1_source_update({"name": "x"}, {"version": "1"})


def test_failed_create_is_reported_and_owned_by_the_feature() -> None:
    edge = FakeEdge(fail_create="/api/suburb-analytics/v1/suburb-comparisons")

    results = _run(edge)

    failed = [result for result in results if not result.passed]
    assert len(failed) == 1
    assert failed[0].owner == "student-3"
    assert failed[0].operation == "create"
    assert "invalid_request" in failed[0].detail


def test_cleanup_runs_even_when_the_read_back_fails() -> None:
    edge = FakeEdge()
    original = edge.__call__

    def broken_read(request: httpx.Request) -> httpx.Response:
        if (
            request.method == "GET"
            and "/api/buyer-workspaces/v1/buyer-cases/" in request.url.path
            and edge.store["/api/buyer-workspaces/v1/buyer-cases"]
        ):
            raise httpx.ReadTimeout("slow", request=request)
        return original(request)

    with httpx.Client(transport=httpx.MockTransport(broken_read)) as client:
        results = Smoke(client, base_url="https://edge.example").run(
            load_features(), expect_ai=False
        )

    assert not edge.store["/api/buyer-workspaces/v1/buyer-cases"]
    failed = [result for result in results if not result.passed]
    assert [result.name for result in failed] == ["CRUD buyer case: request"]
    assert failed[0].owner == "student-5"
    assert failed[0].operation == "request"
    assert any(result.name == "CRUD buyer case: delete" and result.passed for result in results)


@pytest.mark.parametrize(
    ("ai", "expect_ai", "passed", "observed"),
    [
        ("disabled", False, True, False),
        ("unreachable", False, True, None),
        ("available", False, False, True),
        ("available", True, True, True),
        ("disabled", True, False, False),
    ],
)
def test_ai_expectation(ai: str, expect_ai: bool, passed: bool, observed: bool | None) -> None:
    smoke = run_smoke(FakeEdge(ai=ai), expect_ai=expect_ai)

    assert smoke.results[-1].category == "ai"
    assert smoke.results[-1].passed is passed
    assert cloud_smoke.ai_enabled(smoke.ai_state) is observed


def test_main_writes_the_documented_contract_and_sets_the_exit_code(tmp_path: Path) -> None:
    environment = {
        "PROPERTYSCOPE_DEPLOY_SHA": COMMIT.upper(),
        "IMAGE_TAG": COMMIT,
        "ACR_LOGIN_SERVER": "psg20acr.azurecr.io",
    }
    status = main(
        ["--base-url", "https://edge.example/", "--output-dir", str(tmp_path)],
        transport=httpx.MockTransport(FakeEdge()),
        environment=environment,
    )

    assert status == 0
    document = json.loads((tmp_path / "cloud-smoke.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == 2
    assert document["passed"] is True
    assert document["base_url"] == "https://edge.example"
    assert document["commit_sha"] == COMMIT
    assert document["image_tag"] == COMMIT
    assert document["registry"] == "psg20acr.azurecr.io"
    assert document["ai_enabled"] is False and document["ai_state"] == "disabled"
    assert document["images_source"] == "docker-compose.azure.yml with IMAGE_TAG"
    assert set(document["images"]) == set(cloud_smoke.azure_image_services())
    assert (
        document["images"]["f1-backend"] == f"psg20acr.azurecr.io/propertyscope/f1-backend:{COMMIT}"
    )
    assert "caddy" not in " ".join(document["images"])  # third-party mirrors are not ours
    assert document["summary"]["by_owner"]["student-1"]["failed"] == 0
    check = document["checks"][0]
    assert set(check) == {
        "name",
        "owner",
        "category",
        "passed",
        "detail",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "operation",
    }
    markdown = (tmp_path / "cloud-smoke.md").read_text(encoding="utf-8")
    assert "**PASSED**" in markdown
    assert "CRUD source definition: update" in markdown
    assert f"`{COMMIT}`" in markdown

    status = main(
        ["--base-url", "https://edge.example", "--output-dir", str(tmp_path)],
        transport=httpx.MockTransport(FakeEdge(ai="available")),
        environment={},
    )
    assert status == 1
    document = json.loads((tmp_path / "cloud-smoke.json").read_text(encoding="utf-8"))
    assert document["commit_sha"] is None and document["images"] == {}
    assert document["ai_enabled"] is True


def test_cli_identity_wins_over_the_environment_and_explicit_images_replace_derived(
    tmp_path: Path,
) -> None:
    digest = "psg20acr.azurecr.io/propertyscope/f1-backend@sha256:" + "a" * 64
    status = main(
        [
            "--base-url",
            "https://edge.example",
            "--output-dir",
            str(tmp_path),
            "--commit-sha",
            COMMIT,
            "--image",
            f"f1-backend={digest}",
            "--skip-ai-check",
        ],
        transport=httpx.MockTransport(FakeEdge()),
        environment={"PROPERTYSCOPE_DEPLOY_SHA": "f" * 40, "IMAGE_TAG": "latest"},
    )

    assert status == 0
    document = json.loads((tmp_path / "cloud-smoke.json").read_text(encoding="utf-8"))
    assert document["commit_sha"] == COMMIT
    assert document["images"] == {"f1-backend": digest}
    assert document["images_source"] == "--image arguments"
    assert document["ai_enabled"] is None and document["ai_state"] == "not_checked"


def test_vm_log_images_replace_the_derived_list_with_what_the_vm_runs(tmp_path: Path) -> None:
    caddy = "registry:5000/propertyscope/mirror/caddy:2.10.2-alpine@sha256:" + "c" * 64
    backend = f"registry:5000/propertyscope/f1-backend:{COMMIT}@sha256:" + "b" * 64
    log = tmp_path / "vm-deploy.log"
    log.write_text(
        "[stdout]\n"
        'PROPERTYSCOPE_IMAGES={"f1-backend":"stale"}\n'
        f'PROPERTYSCOPE_IMAGES={{"f1-backend":"{backend}","shared-edge-proxy":"{caddy}"}}\r\n'
        'PROPERTYSCOPE_RESULT={"action":"deploy"}\nPROPERTYSCOPE_EXIT=0\n',
        encoding="utf-8",
    )
    status = main(
        [
            *("--base-url", "https://edge.example", "--output-dir", str(tmp_path / "out")),
            *("--vm-log", str(log), "--skip-ai-check", "--no-crud"),
        ],
        transport=httpx.MockTransport(FakeEdge()),
        environment={"IMAGE_TAG": COMMIT, "PROPERTYSCOPE_DEPLOY_SHA": COMMIT},
    )
    assert status == 0
    document = json.loads((tmp_path / "out" / "cloud-smoke.json").read_text(encoding="utf-8"))
    assert document["images"] == {"f1-backend": backend, "shared-edge-proxy": caddy}
    assert document["images_source"] == cloud_smoke.VM_IMAGES_SOURCE


def test_a_cut_off_or_missing_vm_image_line_falls_back_to_the_derived_list() -> None:
    # run-command keeps only the tail of the output: a truncated line must not be trusted.
    assert cloud_smoke.vm_images('PROPERTYSCOPE_IMAGES={"f1-backend":"reg/x:1",\n') == {}
    assert cloud_smoke.vm_images("PROPERTYSCOPE_IMAGES={}\n") == {}
    assert cloud_smoke.vm_images('PROPERTYSCOPE_IMAGES={"a":1}\n') == {}
    identity = cloud_smoke.deployment_identity(
        commit_sha=COMMIT, image_tag=COMMIT, registry="r.io", services=("f1-backend",), observed={}
    )
    assert identity.images_source == "docker-compose.azure.yml with IMAGE_TAG"
    with pytest.raises(ValueError, match="invalid image reference"):
        cloud_smoke.deployment_identity(
            commit_sha=None, image_tag=None, registry=None, observed={"f1-backend": "bad ref"}
        )


def test_an_unreadable_vm_log_is_an_argument_error(tmp_path: Path) -> None:
    status = main(
        [
            *("--base-url", "https://edge.example", "--output-dir", str(tmp_path)),
            *("--vm-log", str(tmp_path / "missing.log")),
        ],
        environment={},
    )
    assert status == 2


@pytest.mark.parametrize(
    "arguments",
    [
        ["--commit-sha", "abc123"],
        ["--image-tag", "bad tag"],
        ["--registry", "https://example.azurecr.io"],
        ["--image", "no-separator"],
        ["--image", "Bad_Service=registry/x:y"],
    ],
    ids=["short-sha", "tag-with-space", "registry-with-scheme", "image-no-equals", "bad-service"],
)
def test_main_rejects_an_invalid_deployment_identity(tmp_path: Path, arguments: list[str]) -> None:
    status = main(
        ["--base-url", "https://edge.example", "--output-dir", str(tmp_path), *arguments],
        environment={},
    )
    assert status == 2
    assert not (tmp_path / "cloud-smoke.json").exists()


def test_main_rejects_a_base_url_without_a_scheme(tmp_path: Path) -> None:
    assert main(["--base-url", "edge.example", "--output-dir", str(tmp_path)]) == 2


def test_azure_image_services_reads_only_commit_tagged_images(tmp_path: Path) -> None:
    compose = tmp_path / "docker-compose.azure.yml"
    compose.write_text(
        "services:\n"
        "  a:\n    image: ${ACR_LOGIN_SERVER:?x}/propertyscope/f1-backend:${IMAGE_TAG:?x}\n"
        "  b:\n    image: ${ACR_LOGIN_SERVER:?x}/propertyscope/mirror/caddy:${CADDY_IMAGE_TAG:-2}\n"
        "  c:\n    image: ${ACR_LOGIN_SERVER:?x}/propertyscope/f1-backend:${IMAGE_TAG:?x}\n",
        encoding="utf-8",
    )

    assert cloud_smoke.azure_image_services(compose) == ("f1-backend",)
    assert cloud_smoke.azure_image_services(tmp_path / "absent.yml") == ()
    assert "shared-frontend" in cloud_smoke.azure_image_services()


def test_the_fixture_document_is_the_real_smoke_shape() -> None:
    document = smoke_document(
        base_url="https://edge.example", commit_sha=COMMIT, registry="psg20acr.azurecr.io"
    )

    assert document == smoke_document(
        base_url="https://edge.example", commit_sha=COMMIT, registry="psg20acr.azurecr.io"
    )
    assert document["passed"] is True
    assert {check["owner"] for check in document["checks"] if check["category"] == "crud"} == {
        f"student-{n}" for n in range(1, 6)
    }


def test_a_failed_delete_is_reported_and_retried_until_the_record_is_gone() -> None:
    edge = FakeEdge()
    original = edge.__call__
    failures = {"left": 1}

    def flaky_delete(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE" and f"{SOURCES}/" in request.url.path and failures["left"]:
            failures["left"] -= 1
            return httpx.Response(503, json={"code": "dependency_unavailable"})
        return original(request)

    with httpx.Client(transport=httpx.MockTransport(flaky_delete)) as client:
        smoke = Smoke(client, base_url="https://edge.example")
        smoke.cleanup_delay = 0
        results = smoke.run(load_features(), expect_ai=False)

    assert not edge.store[SOURCES]
    by_name = {result.name: result for result in results}
    assert by_name["CRUD source definition: delete"].passed is False
    assert "dependency_unavailable" in by_name["CRUD source definition: delete"].detail
    assert by_name["CRUD source definition: cleanup retry"].passed is True
    assert by_name["CRUD source definition: cleanup retry"].operation == "cleanup-retry"


SITE_LOGIN = ("propertyscope", "viewer-password-for-tests")  # pragma: allowlist secret
WRONG_SITE_PASSWORD = "not-the-viewer-password"  # pragma: allowlist secret


def test_site_login_is_proved_then_every_request_signs_in(tmp_path: Path) -> None:
    edge = FakeEdge(site_login=SITE_LOGIN)
    status = main(
        ["--base-url", "https://edge.example", "--output-dir", str(tmp_path), "--site-login"],
        transport=httpx.MockTransport(edge),
        environment={"PROPERTYSCOPE_SITE_PASSWORD": SITE_LOGIN[1]},
    )

    assert status == 0
    document = json.loads((tmp_path / "cloud-smoke.json").read_text(encoding="utf-8"))
    assert document["site_login"] == "enforced"
    by_name = {check["name"]: check for check in document["checks"]}
    assert by_name["Site login required"]["passed"] is True
    assert by_name["Site login required"]["status_code"] == 401
    assert "challenge Basic" in by_name["Site login required"]["detail"]
    assert by_name["Edge liveness stays public"]["passed"] is True
    # Only the two deliberate anonymous probes went out without the viewer login.
    assert edge.anonymous == ["/", "/healthz"]
    assert "Site-wide login: enforced" in (tmp_path / "cloud-smoke.md").read_text(encoding="utf-8")


def test_an_edge_without_the_site_login_fails_the_check(tmp_path: Path) -> None:
    status = main(
        ["--base-url", "https://edge.example", "--output-dir", str(tmp_path), "--site-login"],
        transport=httpx.MockTransport(FakeEdge(site_login=SITE_LOGIN, enforce_site_login=False)),
        environment={"PROPERTYSCOPE_SITE_PASSWORD": SITE_LOGIN[1]},
    )

    assert status == 1
    document = json.loads((tmp_path / "cloud-smoke.json").read_text(encoding="utf-8"))
    assert document["site_login"] == "not_enforced"
    failed = [check["name"] for check in document["checks"] if not check["passed"]]
    assert failed == ["Site login required"]


def test_a_wrong_site_password_fails_every_page_behind_the_login(tmp_path: Path) -> None:
    status = main(
        ["--base-url", "https://edge.example", "--output-dir", str(tmp_path), "--site-login"],
        transport=httpx.MockTransport(FakeEdge(site_login=SITE_LOGIN)),
        environment={"PROPERTYSCOPE_SITE_PASSWORD": WRONG_SITE_PASSWORD},
    )

    assert status == 1
    document = json.loads((tmp_path / "cloud-smoke.json").read_text(encoding="utf-8"))
    by_name = {check["name"]: check for check in document["checks"]}
    assert by_name["Site login required"]["passed"] is True
    assert by_name["Shared home page"]["status_code"] == 401


def test_site_login_needs_the_password_from_the_environment(tmp_path: Path) -> None:
    status = main(
        ["--base-url", "https://edge.example", "--output-dir", str(tmp_path), "--site-login"],
        environment={"PROPERTYSCOPE_SITE_USER": "propertyscope"},
    )
    assert status == 2
    assert not (tmp_path / "cloud-smoke.json").exists()


def test_without_site_login_the_document_records_not_checked(tmp_path: Path) -> None:
    assert (
        main(
            ["--base-url", "https://edge.example", "--output-dir", str(tmp_path)],
            transport=httpx.MockTransport(FakeEdge()),
            environment={},
        )
        == 0
    )
    document = json.loads((tmp_path / "cloud-smoke.json").read_text(encoding="utf-8"))
    assert document["site_login"] == "not_checked"
