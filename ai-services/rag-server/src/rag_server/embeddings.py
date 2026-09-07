"""Local CPU embeddings with explicit preparation and injectable deterministic fixtures."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
MANIFEST_NAME = "propertyscope-model.json"


class EmbeddingUnavailableError(RuntimeError):
    """The explicitly prepared local embedding dependency is unavailable."""


class Embedder(Protocol):
    identity: str
    dimensions: int

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]: ...


def normalized_vector(vector: Sequence[float], dimensions: int) -> list[float]:
    """Reject corrupt embeddings before persistence or similarity arithmetic."""
    values = [float(value) for value in vector]
    if len(values) != dimensions or not all(math.isfinite(value) for value in values):
        raise ValueError("embedding dimensions or finite-value validation failed")
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("embedding must have a finite positive norm")
    return [value / norm for value in values]


class FixtureEmbedder:
    """Explicit lexical hashing fixture, never evidence of semantic model quality."""

    identity = "fixture-lexical-sha256-v1"
    dimensions = DIMENSIONS

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                slot = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % self.dimensions
                vector[slot] += 1
            if not any(vector):
                vector[0] = 1
            vectors.append(normalized_vector(vector, self.dimensions))
        return vectors


class UnavailableEmbedder:
    identity = "unprepared-local-model"
    dimensions = DIMENSIONS

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        raise EmbeddingUnavailableError("Run rag-server prepare-model before semantic retrieval")


def _artifact_hashes(cache_path: Path) -> dict[str, str]:
    files = sorted(
        path
        for path in cache_path.rglob("*")
        if path.is_file()
        and path.suffix in {".onnx", ".json", ".txt"}
        and path.name != MANIFEST_NAME
    )
    if not any(path.suffix == ".onnx" for path in files):
        raise EmbeddingUnavailableError("Prepared cache contains no ONNX model")
    result: dict[str, str] = {}
    for path in files:
        with path.open("rb") as stream:
            result[path.relative_to(cache_path).as_posix()] = hashlib.file_digest(
                stream, "sha256"
            ).hexdigest()
    return result


def prepare_model(cache_path: Path) -> str:
    """The only operation allowed to acquire model assets from the network."""
    from fastembed import TextEmbedding

    cache_path.mkdir(parents=True, exist_ok=True)
    model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(cache_path), threads=2)
    normalized_vector(next(iter(model.embed(["model readiness"]))).tolist(), DIMENSIONS)
    artifacts = _artifact_hashes(cache_path)
    manifest = {"model": MODEL_NAME, "dimensions": DIMENSIONS, "artifacts": artifacts}
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    (cache_path / MANIFEST_NAME).write_text(payload, encoding="utf-8")
    return f"{MODEL_NAME}@{hashlib.sha256(payload.encode()).hexdigest()}"


class LocalEmbedder:
    dimensions = DIMENSIONS

    def __init__(self, cache_path: Path) -> None:
        from fastembed import TextEmbedding

        try:
            manifest = json.loads((cache_path / MANIFEST_NAME).read_text(encoding="utf-8"))
            actual = {
                "model": MODEL_NAME,
                "dimensions": DIMENSIONS,
                "artifacts": _artifact_hashes(cache_path),
            }
            if manifest != actual:
                raise EmbeddingUnavailableError("Prepared model artifacts changed; prepare again")
            payload = json.dumps(actual, sort_keys=True, separators=(",", ":"))
            self.identity = f"{MODEL_NAME}@{hashlib.sha256(payload.encode()).hexdigest()}"
            self._model = TextEmbedding(
                model_name=MODEL_NAME,
                cache_dir=str(cache_path),
                threads=2,
                local_files_only=True,
            )
        except (OSError, ValueError) as exc:
            raise EmbeddingUnavailableError(
                "Local model is not prepared or cannot be loaded"
            ) from exc

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        try:
            if query:
                vectors = self._model.query_embed(list(texts))
            else:
                vectors = self._model.passage_embed(list(texts), batch_size=16)
            return [normalized_vector(vector.tolist(), self.dimensions) for vector in vectors]
        except Exception as exc:
            raise EmbeddingUnavailableError("Local embedding execution failed") from exc
