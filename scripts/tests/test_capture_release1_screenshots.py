"""Release evidence requires correlated public outcomes, not just a terminal screenshot."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from scripts import build_release1_report as report
from scripts import capture_release1_screenshots as capture
from scripts.release1_capture_evidence import CaptureError, correlate_run, verified_evidence

RUN = "10000000-0000-4000-8000-000000000001"
CALL = "10000000-0000-4000-8000-000000000002"
VERSION = "a" * 64
F1 = capture.FEATURES[1]


def capabilities() -> dict[str, Any]:
    return {
        "services": [{"id": name, "status": "ready", "enabled": True} for name in ("mcp", "rag")],
        "grounding_features": [F1.key],
    }


def detail(mode: str = "rag") -> dict[str, Any]:
    citation = {
        "citation_id": "source-1",
        "feature_key": F1.key,
        "corpus_id": F1.corpus,
        "corpus_version": VERSION,
        "document_id": "sales-history",
        "chunk_id": "sales-history-1",
        "title": "Sales evidence limitations",
        "excerpt": "Published project guidance explains bounded sales evidence.",
        "source_uri": "https://example.test/sales",
        "content_hash": "b" * 64,
        "score": 0.8,
    }
    final = {
        "summary": "Evidence-backed answer",
        "confidence": "moderate",
        "confidence_reason": "One relevant project-guidance source",
        "corpus_version": VERSION,
        "grounding_status": "ready",
        "citations": [citation],
        "findings": [
            {
                "kind": "guidance",
                "text": "Project guidance explains the coverage limits.",
                "citation_ids": ["source-1"],
                "tool_call_ids": [],
            }
        ],
        "evidence_gaps": [],
    }
    retrieval = {
        "feature_key": F1.key,
        "corpus_id": F1.corpus,
        "corpus_version": VERSION,
        "status": "ready",
        "citations": [citation],
        "query": "PRIVATE QUERY",
    }
    result: dict[str, Any] = {
        "call_id": "retrieval-call",
        "outcome": "succeeded",
        "retrieval": retrieval,
        "content": {"status": "ready"},
        "evidence_references": ["service:rag"],
    }
    steps = [
        {
            "phase": "act",
            "input": {
                "tool_calls": [
                    {
                        "id": "retrieval-call",
                        "tool_name": "context.retrieve.v1",
                        "tool_version": "v1",
                        "arguments": {"query": "PRIVATE QUERY"},
                    }
                ]
            },
            "output": {"tool_results": [result], "private_reasoning": "PRIVATE REASONING"},
        }
    ]
    if mode == "mcp":
        final["findings"].append(
            {
                "kind": "tool_fact",
                "text": "Published releases were inspected.",
                "citation_ids": [],
                "tool_call_ids": [CALL],
            }
        )
        steps[0]["input"]["tool_calls"].append(
            {
                "id": CALL,
                "tool_name": F1.expected_tool,
                "tool_version": "v1",
                "arguments": {"secret": "SECRET TOOL ARGUMENT"},
            }
        )
        steps[0]["output"]["tool_results"].append(
            {
                "call_id": CALL,
                "outcome": "succeeded",
                "content": {"items": [{"private_note": "PRIVATE USER RECORD"}], "count": 1},
                "evidence_references": ["service:backend", "status:200", "transport:mcp"],
            }
        )
    if mode == "insufficient":
        retrieval.update(status="no_match", citations=[])
        final.update(
            confidence="insufficient",
            grounding_status="no_match",
            citations=[],
            findings=[],
            evidence_gaps=["No relevant context"],
        )
    steps.append(
        {
            "phase": "adapt",
            "input": {"prompt": "SECRET PROMPT"},
            "output": {
                "model_invocation": {
                    "provider": "openai",
                    "model": "example-model",
                    "prompt_id": "adapt",
                    "prompt_version": "v9",
                    "prompt_hash": "c" * 64,
                    "rendered_prompt": "SECRET PROMPT",
                    "provider_request_id": "PRIVATE PROVIDER ID",
                }
            },
        }
    )
    return {
        "run": {
            "id": RUN,
            "feature_key": F1.key,
            "status": "succeeded",
            "grounding": {"corpus_id": F1.corpus},
            "final_result": final,
            "request_id": "public-request",
            "created_at": "2026-10-03T01:00:00Z",
            "model_profile": "test-profile",
            "prompt_set": "default.v9",
            "objective": "PRIVATE QUESTION",
        },
        "steps": steps,
    }


def verify(
    value: dict[str, Any], mode: str = "rag", ready: dict[str, Any] | None = None
) -> dict[str, Any]:
    return verified_evidence(
        value,
        feature_key=F1.key,
        corpus_id=F1.corpus,
        mode=mode,
        expected_tool=F1.expected_tool,
        run_id=RUN,
        capabilities=ready or capabilities(),
    )


def test_every_report_screenshot_has_a_capture_entry() -> None:
    source = report.SOURCE.read_text(encoding="utf-8")
    referenced = set(re.findall(r"assets/release-1/screenshots/([\w-]+)\.png", source))
    assert referenced == {shot.name for shot in capture.SHOTS}


def test_all_five_features_have_three_explicit_ready_questions() -> None:
    for number in range(1, 6):
        shots = [shot for shot in capture.SHOTS if shot.feature == number]
        assert {shot.mode for shot in shots} == {"mcp", "rag", "insufficient"}
        assert all(shot.question for shot in shots)
    for number, feature in capture.FEATURES.items():
        corpus = json.loads(
            (capture.REPOSITORY_ROOT / f"student-{number}/config/rag/corpus.json").read_text()
        )
        assert (feature.key, feature.corpus) == (corpus["feature_key"], corpus["corpus_id"])


def test_list_has_no_stale_adoption_placeholders(capsys: pytest.CaptureFixture[str]) -> None:
    assert capture.main(["--list", "--only", "feature-4"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert all("ready" in line and "pending" not in line for line in lines)


def test_unknown_only_does_not_silently_succeed() -> None:
    with pytest.raises(SystemExit) as error:
        capture.main(["--list", "--only", "missing-feature"])
    assert error.value.code == 2


@pytest.mark.parametrize("mode", ["rag", "mcp", "insufficient"])
def test_acceptance_projects_only_public_metadata(mode: str) -> None:
    evidence = verify(detail(mode), mode)
    assert evidence["status"] == "succeeded"
    assert evidence["corpus_version"] == VERSION
    assert evidence["tools"][0]["transport"] == "rag"
    assert evidence["models"][0]["prompt_version"] == "v9"
    serialised = json.dumps(evidence)
    for private in (
        "PRIVATE",
        "SECRET",
        "query",
        "objective",
        "arguments",
        "rendered_prompt",
        "provider_request_id",
        "private_reasoning",
    ):
        assert private not in serialised
    if mode == "mcp":
        assert evidence["tools"][1]["transport"] == "mcp"


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "failed"),
        ("status", "cancelled"),
        ("status", "review_required"),
        ("id", "other-run"),
        ("feature_key", "other-feature"),
        ("grounding", {"corpus_id": "other-corpus"}),
    ],
)
def test_terminal_states_and_scope_mismatch_fail(field: str, value: object) -> None:
    payload = detail()
    payload["run"][field] = value
    with pytest.raises(CaptureError):
        verify(payload)


@pytest.mark.parametrize("status", ["disabled", "unavailable"])
def test_not_ready_services_are_not_valid_insufficient_context(status: str) -> None:
    ready = capabilities()
    ready["services"][1]["status"] = status
    with pytest.raises(CaptureError, match="runtime is not ready"):
        verify(detail("insufficient"), "insufficient", ready)


def test_mcp_requires_authenticated_transport_marker_and_answer_support() -> None:
    payload = detail("mcp")
    payload["steps"][0]["output"]["tool_results"][1]["evidence_references"].remove("transport:mcp")
    with pytest.raises(CaptureError, match="through MCP"):
        verify(payload, "mcp")
    payload = detail("mcp")
    payload["run"]["final_result"]["findings"] = payload["run"]["final_result"]["findings"][:1]
    with pytest.raises(CaptureError, match="visible answer finding"):
        verify(payload, "mcp")


def test_tool_failure_or_missing_correlated_result_is_rejected() -> None:
    payload = detail("mcp")
    payload["steps"][0]["output"]["tool_results"][1]["outcome"] = "failed"
    with pytest.raises(CaptureError, match="did not succeed"):
        verify(payload, "mcp")
    payload["steps"][0]["output"]["tool_results"].pop()
    with pytest.raises(CaptureError, match="no matching result"):
        verify(payload, "mcp")


@pytest.mark.parametrize(
    "changed", ["feature_key", "corpus_id", "corpus_version", "excerpt", "content_hash"]
)
def test_citation_must_match_actual_retrieved_passage(changed: str) -> None:
    payload = copy.deepcopy(detail())
    payload["run"]["final_result"]["citations"][0] = dict(
        payload["run"]["final_result"]["citations"][0], **{changed: "invented"}
    )
    with pytest.raises(CaptureError, match="citation"):
        verify(payload)


def test_tool_fact_only_answer_does_not_count_as_rag_demonstration() -> None:
    payload = detail("mcp")
    payload["run"]["final_result"].update(
        citations=[], findings=[payload["run"]["final_result"]["findings"][1]]
    )
    with pytest.raises(CaptureError, match="no grounded cited answer"):
        verify(payload)


def test_unavailable_retrieval_cannot_count_as_valid_refusal() -> None:
    payload = detail("insufficient")
    payload["steps"][0]["output"]["tool_results"][0]["retrieval"]["status"] = "unavailable"
    with pytest.raises(CaptureError, match="unavailable rather"):
        verify(payload, "insufficient")


def test_unsupported_question_that_now_matches_corpus_is_rejected() -> None:
    with pytest.raises(CaptureError, match="explicit insufficient"):
        verify(detail(), "insufficient")


def test_feature_projection_can_hide_config_and_translate_display_wording() -> None:
    durable = detail()
    owning = copy.deepcopy(durable)
    for key in ("feature_key", "grounding", "model_profile", "prompt_set", "objective"):
        owning["run"].pop(key)
    owning["run"]["final_result"]["summary"] = "Translated domain names in the same answer"
    assert correlate_run(owning, durable) is durable


@pytest.mark.parametrize(
    "difference", ["id", "status", "request_id", "confidence", "citations", "findings"]
)
def test_owning_projection_must_match_durable_outcome_and_support(difference: str) -> None:
    durable = detail()
    owning = copy.deepcopy(durable)
    if difference in ("id", "status", "request_id"):
        owning["run"][difference] = "different"
    elif difference == "findings":
        owning["run"]["final_result"]["findings"][0]["citation_ids"] = ["another-source"]
    else:
        owning["run"]["final_result"][difference] = [] if difference == "citations" else "low"
    with pytest.raises(CaptureError, match=r"differs|different"):
        correlate_run(owning, durable)


class FakeLocator:
    def __init__(self, page: FakePage, selector: str) -> None:
        self.page, self.selector = page, selector

    @property
    def first(self) -> FakeLocator:
        return self

    @property
    def last(self) -> FakeLocator:
        return self

    def wait_for(self, **_options: Any) -> None:
        self.page.actions.append(("wait", self.selector))

    def click(self) -> None:
        self.page.actions.append(("click", self.selector))

    def evaluate(self, _code: str) -> None:
        self.page.actions.append(("evaluate", self.selector))

    def select_option(self, value: str) -> None:
        self.page.actions.append(("select", self.selector, value))

    def fill(self, value: str) -> None:
        self.page.actions.append(("fill", self.selector, value))

    def press(self, value: str) -> None:
        self.page.actions.append(("press", self.selector, value))

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self.page, selector)

    def count(self) -> int:
        return int(self.page.turn_error) if self.selector == ".ps-ai-chat__turn-error" else 1

    def get_attribute(self, _name: str) -> str:
        return RUN

    def inner_text(self) -> str:
        return "Recorded public answer"

    def bounding_box(self) -> dict[str, float] | None:
        return self.page.focus_box

    def screenshot(self, *, path: str, **_kwargs: Any) -> None:
        self.page.actions.append(("element-screenshot", self.selector))
        Path(path).write_bytes(b"real element screenshot represented by fake browser")


class FakePage:
    def __init__(self) -> None:
        self.actions: list[tuple[str, ...]] = []
        self.turn_error = False
        self.posted_context: dict[str, str] = {}
        self.nested_start = False
        self.focus_box: dict[str, float] | None = {"x": 140, "y": 120, "width": 840, "height": 600}
        self.viewport: dict[str, int] = dict(capture.VIEWPORT)

    def goto(self, url: str, **_options: Any) -> Any:
        self.actions.append(("goto", url))
        return type("Loaded", (), {"status": 200})()

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def on(self, _event: str, _callback: Any) -> None:
        pass

    def set_viewport_size(self, viewport: dict[str, int]) -> None:
        self.viewport = dict(viewport)

    def screenshot(self, *, path: str, **_kwargs: Any) -> None:
        Path(path).write_bytes(b"test screenshot bytes")

    def expect_response(self, predicate: Any, **_kwargs: Any) -> Any:
        request = type(
            "Request", (), {"method": "POST", "post_data_json": {"context": self.posted_context}}
        )()
        response = type(
            "Response",
            (),
            {
                "request": request,
                "url": "http://localhost:5100/api/data-platform/v1/assistant/turns",
                "status": 201,
                "json": lambda _self: {"run": {"id": RUN}} if self.nested_start else {"id": RUN},
            },
        )()
        assert predicate(response)

        class Expected:
            value = response

            def __enter__(self) -> Any:
                return self

            def __exit__(self, *_args: Any) -> None:
                pass

        return Expected()


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    def new_page(self) -> FakePage:
        return self.page

    def close(self) -> None:
        pass


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    def new_context(self, **_kwargs: Any) -> FakeContext:
        return FakeContext(self.page)

    def close(self) -> None:
        pass


def fake_capture(monkeypatch: pytest.MonkeyPatch, page: FakePage, payload: dict[str, Any]) -> None:
    class Playwright:
        chromium = type("Chromium", (), {"launch": lambda _self, **_kwargs: FakeBrowser(page)})()

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

    monkeypatch.setattr(capture, "sync_playwright", Playwright)
    monkeypatch.setattr(capture, "_software", lambda: ("d" * 40, False))
    monkeypatch.setattr(
        capture,
        "_get",
        lambda _page, _base, path: capabilities() if path.endswith("capabilities") else payload,
    )
    monkeypatch.setattr(capture, "setup_feature", lambda *_args: {})


def test_capture_writes_correlated_images_and_public_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page = FakePage()
    fake_capture(monkeypatch, page, detail("mcp"))
    shot = next(item for item in capture.SHOTS if item.name == "feature-1-mcp")
    assert capture.capture([shot], base_url="http://localhost:5100", output=tmp_path) == []
    manifest = json.loads((tmp_path / "feature-1-mcp.json").read_text())
    assert manifest["software_sha"] == "d" * 40
    assert manifest["tracked_worktree_dirty"] is False
    assert manifest["run_id"] == RUN
    assert len(manifest["images"]) == 3
    assert all((tmp_path / item["file"]).exists() for item in manifest["images"])
    assert ("evaluate", f'details[data-disclosure="tool:{CALL}"]') in page.actions
    assert not list(tmp_path.glob(".*.png"))


def test_supported_rag_has_actual_answer_and_cited_element_companions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page = FakePage()
    fake_capture(monkeypatch, page, detail())
    shot = next(item for item in capture.SHOTS if item.name == "feature-1-rag")
    assert capture.capture([shot], base_url="http://localhost:5100", output=tmp_path) == []
    manifest = json.loads((tmp_path / "feature-1-rag.json").read_text())
    focused = [item for item in manifest["images"] if item["capture"] == "element"]
    assert {item["file"] for item in focused} == {
        "feature-1-rag.answer.png",
        "feature-1-rag.citation.png",
    }
    assert all(item["viewport"]["width"] == capture.FOCUS_WIDTH for item in focused)
    assert all(item["element_size"] == {"width": 840, "height": 600} for item in focused)
    assert ("element-screenshot", ".ps-ai-chat__message--assistant") in page.actions
    assert ("element-screenshot", 'details[data-disclosure="source:source-1"]') in page.actions


def test_focus_uses_taller_real_viewport_to_avoid_scroll_panel_clipping(tmp_path: Path) -> None:
    page = FakePage()
    page.focus_box = {"x": 140, "y": 120, "width": 840, "height": 1400}
    destination = tmp_path / "answer.png"
    metadata = capture._focused_image(page, page.locator(".answer"), destination)  # type: ignore[arg-type]
    assert metadata["viewport"] == {"width": 1100, "height": 1640}
    assert destination.exists()
    assert ("element-screenshot", ".answer") in page.actions


@pytest.mark.parametrize(
    "box",
    [
        None,
        {"x": 0, "y": 0, "width": 200, "height": 600},
        {"x": 0, "y": 0, "width": 800, "height": 40},
        {"x": 0, "y": 0, "width": 800, "height": 6000},
        {"x": 500, "y": 0, "width": 800, "height": 600},
        {"x": 0, "y": 1000, "width": 800, "height": 600},
    ],
)
def test_unreadable_or_clipped_focus_does_not_promote_any_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, box: dict[str, float] | None
) -> None:
    page = FakePage()
    page.focus_box = box
    fake_capture(monkeypatch, page, detail("mcp"))
    original = tmp_path / "feature-1-mcp.png"
    original.write_bytes(b"original verified evidence")
    shot = next(item for item in capture.SHOTS if item.name == "feature-1-mcp")
    assert capture.capture([shot], base_url="http://localhost:5100", output=tmp_path)
    assert original.read_bytes() == b"original verified evidence"
    assert not (tmp_path / "feature-1-mcp.json").exists()
    assert not list(tmp_path.glob(".*.png"))


def test_nested_feature_start_response_matches_visible_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page = FakePage()
    page.nested_start = True
    fake_capture(monkeypatch, page, detail("mcp"))
    shot = next(item for item in capture.SHOTS if item.name == "feature-1-mcp")
    assert capture.capture([shot], base_url="http://localhost:5100", output=tmp_path) == []


@pytest.mark.parametrize("failure", ["turn-error", "wrong-context", "wrong-run", "wrong-citation"])
def test_failed_capture_preserves_prior_evidence_and_removes_staging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    page = FakePage()
    payload = detail()
    if failure == "turn-error":
        page.turn_error = True
    elif failure == "wrong-run":
        payload["run"]["id"] = "another-run"
    elif failure == "wrong-citation":
        payload = copy.deepcopy(payload)
        payload["run"]["final_result"]["citations"][0] = dict(
            payload["run"]["final_result"]["citations"][0], corpus_id="wrong"
        )
    fake_capture(monkeypatch, page, payload)
    if failure == "wrong-context":
        monkeypatch.setattr(capture, "setup_feature", lambda *_args: {"locality": "SYDNEY"})
    original = tmp_path / "feature-1-rag.png"
    original.write_bytes(b"original verified evidence")
    shot = next(item for item in capture.SHOTS if item.name == "feature-1-rag")
    problems = capture.capture([shot], base_url="http://localhost:5100", output=tmp_path)
    assert len(problems) == 1
    assert original.read_bytes() == b"original verified evidence"
    assert not (tmp_path / "feature-1-rag.json").exists()
    assert not list(tmp_path.glob(".*.png"))


@pytest.mark.parametrize(
    "number,key,fragment",
    [
        (2, "market_case_id", "#assistant"),
        (4, "site_review_id", "#site-reviews/"),
        (5, "buyer_case_id", "#buyer-cases/"),
    ],
)
def test_existing_resources_are_selected_without_mutation(
    monkeypatch: pytest.MonkeyPatch, number: int, key: str, fragment: str
) -> None:
    page = FakePage()
    reads = []

    def read(_page: Any, _base: str, path: str) -> dict[str, Any]:
        reads.append(path)
        return {"items": [{"id": RUN}]}

    monkeypatch.setattr(capture, "_get", read)
    shot = next(item for item in capture.SHOTS if item.feature == number)
    context = capture.setup_feature(page, shot, "http://localhost:5100", {number: RUN})  # type: ignore[arg-type]
    assert context[key] == RUN
    assert fragment in next(action[1] for action in page.actions if action[0] == "goto")
    assert reads and not any(
        "create" in action[1] or "delete" in action[1] for action in page.actions
    )
    if number == 2:
        assert ("click", f'#case-list [data-case-id="{RUN}"]') in page.actions


def test_suburb_context_uses_real_context_editor_and_exact_published_locality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage()
    monkeypatch.setattr(capture, "_get", lambda *_args: {"items": ["SYDNEY", "PARRAMATTA"]})
    shot = next(item for item in capture.SHOTS if item.feature == 3)
    context = capture.setup_feature(page, shot, "http://localhost:5100", {3: "PARRAMATTA"})  # type: ignore[arg-type]
    assert context == {"route": "suburbs/detail", "locality": "PARRAMATTA"}
    assert (
        "select",
        "#assistant-root .ps-ai-chat__context-editor select",
        "locality",
    ) in page.actions
    assert ("fill", "#assistant-root input[name='locality']", "PARRAMATTA") in page.actions
    with pytest.raises(CaptureError, match="exact published"):
        capture.setup_feature(page, shot, "http://localhost:5100", {3: "INVENTED"})  # type: ignore[arg-type]


def test_missing_seed_requires_explicit_existing_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capture, "_get", lambda *_args: {"items": []})
    shot = next(item for item in capture.SHOTS if item.feature == 2)
    with pytest.raises(CaptureError, match="resource is absent"):
        capture.setup_feature(FakePage(), shot, "http://localhost:5100", {})  # type: ignore[arg-type]


def test_output_can_be_outside_repository(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    observed = []
    monkeypatch.setattr(capture, "capture", lambda shots, **kwargs: observed.append(kwargs) or [])
    assert (
        capture.main(
            ["--only", "feature-1-rag", "--output", str(tmp_path), "--feature-4-review", RUN]
        )
        == 0
    )
    assert observed[0]["output"] == tmp_path
    assert observed[0]["resources"] == {4: RUN}


def test_credentials_in_capture_origin_are_rejected_before_browser_starts(tmp_path: Path) -> None:
    with pytest.raises(CaptureError, match="without credentials"):
        capture.capture([], base_url="http://secret:password@localhost:5100", output=tmp_path)


@pytest.mark.parametrize(
    "status,payload", [(503, {"detail": "PRIVATE ERROR BODY"}), (200, ["PRIVATE VALUES"])]
)
def test_public_read_rejects_http_errors_and_non_objects_without_leaking_body(
    status: int, payload: object
) -> None:
    response = type("Response", (), {"status": status, "json": lambda _self: payload})()
    page = type(
        "Page", (), {"request": type("Request", (), {"get": lambda *_args, **_kwargs: response})()}
    )()
    with pytest.raises(CaptureError) as error:
        capture._get(page, "http://localhost:5100", "/public/read?q=PRIVATE QUERY")
    assert "PRIVATE" not in str(error.value)


def test_public_read_preserves_only_in_memory_payload_for_validation() -> None:
    payload = {"items": [{"id": RUN}]}
    response = type("Response", (), {"status": 200, "json": lambda _self: payload})()
    page = type(
        "Page", (), {"request": type("Request", (), {"get": lambda *_args, **_kwargs: response})()}
    )()
    assert capture._get(page, "http://localhost:5100", "/public/read") == payload


def test_shared_knowledge_requires_all_five_ready_corpora_and_allowlists_version_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpora = [
        {
            "feature_key": feature.key,
            "corpus_id": feature.corpus,
            "status": "ready",
            "version": {
                "corpus_version": VERSION,
                "document_count": 8,
                "private_credentials": "SECRET",
            },
            "private_field": "SECRET",
        }
        for feature in capture.FEATURES.values()
    ]
    monkeypatch.setattr(capture, "_get", lambda *_args: {"corpora": corpora})
    shot = next(item for item in capture.SHOTS if item.name == "shared-knowledge-sources")
    metadata = capture._shared(FakePage(), shot, "http://localhost:5100", None)  # type: ignore[arg-type]
    assert len(metadata["corpora"]) == 5
    assert "SECRET" not in json.dumps(metadata)
    corpora[4]["status"] = "unavailable"
    with pytest.raises(CaptureError, match="all five"):
        capture._shared(FakePage(), shot, "http://localhost:5100", None)  # type: ignore[arg-type]


def test_shared_activity_selects_supported_run_instead_of_latest_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = "20000000-0000-4000-8000-000000000001"
    failed = "20000000-0000-4000-8000-000000000002"
    reads = []

    def read(_page: Any, _base: str, path: str) -> dict[str, Any]:
        reads.append(path)
        if path.startswith("/api/v1/agent-runs?"):
            return {
                "items": [
                    {"id": failed, "status": "failed", "feature_key": F1.key},
                    {"id": refusal, "status": "succeeded", "feature_key": F1.key},
                    {"id": RUN, "status": "succeeded", "feature_key": F1.key},
                ]
            }
        projected = {
            "run": {
                "id": RUN,
                "feature_key": F1.key,
                "status": "succeeded",
                "created_at": "2026-10-03T00:00:00Z",
            },
            "final_result": detail()["run"]["final_result"],
            "private_model_output": "PRIVATE REASONING",
        }
        if path.endswith(refusal):
            projected["final_result"] = detail("insufficient")["run"]["final_result"]
        return projected

    monkeypatch.setattr(capture, "_get", read)
    shot = next(item for item in capture.SHOTS if item.name == "shared-activity-history")
    page = FakePage()
    metadata = capture._shared(page, shot, "http://localhost:5100", None)  # type: ignore[arg-type]
    assert metadata["run_id"] == RUN
    assert "PRIVATE" not in json.dumps(metadata)
    assert not any(path.endswith(failed) for path in reads)
    assert ("goto", "http://localhost:5100/operations/ai-mode/?run=" + RUN) in page.actions


def test_shared_activity_does_not_capture_failed_or_absent_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shot = next(item for item in capture.SHOTS if item.name == "shared-activity-history")
    monkeypatch.setattr(capture, "_get", lambda *_args: {"items": []})
    with pytest.raises(CaptureError, match="no successful"):
        capture._shared(FakePage(), shot, "http://localhost:5100", None)  # type: ignore[arg-type]
    monkeypatch.setattr(capture, "_get", lambda *_args: {"run": {"status": "failed"}})
    with pytest.raises(CaptureError, match="has not succeeded"):
        capture._shared(FakePage(), shot, "http://localhost:5100", RUN)  # type: ignore[arg-type]


def test_fast_completed_turn_is_verified_when_stop_control_never_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_wait = FakeLocator.wait_for

    def wait(locator: FakeLocator, **options: Any) -> None:
        if locator.selector == capture.STOP_RESPONSE:
            raise capture.PlaywrightTimeoutError("fast response already complete")
        original_wait(locator, **options)

    monkeypatch.setattr(FakeLocator, "wait_for", wait)
    assert capture._ask(FakePage(), "A public question") == RUN  # type: ignore[arg-type]
