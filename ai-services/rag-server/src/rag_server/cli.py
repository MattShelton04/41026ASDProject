"""Explicit operator commands: prepare assets, serve locally, and ingest owned documents."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rag_server.app import create_app
from rag_server.embeddings import prepare_model
from shared_contracts.retrieval import CorpusIngestRequest


def load_manifest(path: Path) -> CorpusIngestRequest:
    """Read explicit local text/Markdown paths confined to the manifest's own directory."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    base = path.resolve().parent
    for document in payload.get("documents", []):
        source_path = document.pop("path", None)
        if source_path is None:
            continue
        resolved = (base / source_path).resolve()
        if not resolved.is_relative_to(base) or resolved.suffix.lower() not in {".md", ".txt"}:
            raise ValueError(
                "Manifest document paths must be local .md/.txt files beneath its directory"
            )
        if resolved.stat().st_size > 240000:
            raise ValueError("Manifest document is too large")
        if "text" in document:
            raise ValueError("Use either path or text, not both")
        document["text"] = resolved.read_text(encoding="utf-8")
    return CorpusIngestRequest.model_validate(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "prepare-model", help="Explicitly download and hash local model assets"
    )
    prepare.add_argument(
        "--cache-path",
        type=Path,
        default=Path(os.getenv("RAG_MODEL_CACHE_PATH", ".propertyscope-runtime/host/rag/models")),
    )
    serve = commands.add_parser("serve", help="Foreground loopback diagnosis server")
    serve.add_argument("--port", type=int, default=5012)
    ingest = commands.add_parser(
        "ingest", help="Replace a registered corpus with a complete local manifest"
    )
    ingest.add_argument("manifest", type=Path)
    ingest.add_argument("--port", type=int, default=5012)
    args = parser.parse_args()
    if args.command == "prepare-model":
        print(json.dumps({"embedding_model": prepare_model(args.cache_path)}))
    elif args.command == "serve":
        create_app().run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)
    else:
        token = os.getenv("RAG_SERVICE_TOKEN", "")
        if len(token) < 16:
            parser.error("Set RAG_SERVICE_TOKEN before ingestion")
        payload = load_manifest(args.manifest)
        request = Request(
            f"http://127.0.0.1:{args.port}/api/v1/corpora/ingest",
            data=payload.model_dump_json().encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        try:
            with urlopen(request, timeout=120) as response:  # noqa: S310 - operator-supplied RAG server URL
                print(response.read(65536).decode())
        except (HTTPError, URLError) as exc:
            parser.exit(1, f"Ingestion failed: {exc}\n")


if __name__ == "__main__":
    main()
