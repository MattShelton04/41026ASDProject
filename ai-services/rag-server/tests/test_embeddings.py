"""Model preparation lifecycle is tested using a fake FastEmbed boundary."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import fastembed
import pytest
from rag_server.embeddings import (
    DIMENSIONS,
    EmbeddingUnavailableError,
    FixtureEmbedder,
    LocalEmbedder,
    prepare_model,
)


class FakeVector:
    def tolist(self) -> list[float]:
        return [1.0] * DIMENSIONS


class FakeModel:
    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        path = Path(kwargs["cache_dir"])
        if not kwargs.get("local_files_only"):
            (path / "model.onnx").write_bytes(b"fake onnx")
            (path / "tokenizer.json").write_text("{}", encoding="utf-8")

    def embed(self, texts: list[str], **kwargs: Any) -> Iterator[FakeVector]:
        return iter(FakeVector() for _ in texts)

    passage_embed = embed
    query_embed = embed


def test_explicit_prepare_hashes_and_offline_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeModel.calls = []
    monkeypatch.setattr(fastembed, "TextEmbedding", FakeModel)
    identity = prepare_model(tmp_path)
    model = LocalEmbedder(tmp_path)
    assert model.identity == identity
    assert FakeModel.calls[-1]["local_files_only"] is True
    assert len(model.embed(["a", "b"])) == 2
    assert len(model.embed(["question"], query=True)[0]) == DIMENSIONS
    (tmp_path / "tokenizer.json").write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(EmbeddingUnavailableError, match="changed"):
        LocalEmbedder(tmp_path)
    assert len(FakeModel.calls) == 2  # Changed assets fail before loading a model.


def test_missing_corrupt_or_no_onnx_manifest_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fastembed, "TextEmbedding", FakeModel)
    with pytest.raises(EmbeddingUnavailableError):
        LocalEmbedder(tmp_path)
    manifest = tmp_path / "propertyscope-model.json"
    manifest.write_text("{", encoding="utf-8")
    with pytest.raises(EmbeddingUnavailableError):
        LocalEmbedder(tmp_path)
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(EmbeddingUnavailableError, match="ONNX"):
        LocalEmbedder(tmp_path)


def test_embedding_execution_failure_is_structured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fastembed, "TextEmbedding", FakeModel)
    prepare_model(tmp_path)
    model = LocalEmbedder(tmp_path)

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("private model diagnostics")

    monkeypatch.setattr(model._model, "passage_embed", fail)
    with pytest.raises(EmbeddingUnavailableError, match="execution failed"):
        model.embed(["a"])
    assert len(FixtureEmbedder().embed(["?!"])[0]) == DIMENSIONS
