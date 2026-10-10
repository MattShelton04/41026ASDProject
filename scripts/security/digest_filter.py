"""detect-secrets custom filter: a hex digest that its own context names as a digest.

The repository pins SHA-256 digests on purpose (content hashes in evidence exports, migration and
asset checksums in tests). detect-secrets' Hex High Entropy plugin flags each one, and the
single-line `--exclude-lines` rule in `policy.py` misses a digest whose name sits on the line
above (`hashlib.sha256(...).hexdigest() == (` then the value) or in prose ("content_sha256 is
"..."). This filter drops a Hex High Entropy finding only when all of these hold:

- the value is exactly a SHA-1, SHA-256 or SHA-512 hex digest (40, 64 or 128 hex characters);
- the same line or one of the two lines above names a digest (sha256, hexdigest, checksum, ...);
- the same line does not name a credential (secret, token, password, api key, ...).

Every other detector (keywords, provider token formats, private keys, Base64 entropy) is
unaffected. Repository-generated tokens use `secrets.token_urlsafe`, which is never pure hex.
detect-secrets loads this file by path (`file://scripts/security/digest_filter.py::...`), so it
must stay standalone: no imports from the `scripts` package.
"""

from __future__ import annotations

import re
from typing import Any

DIGEST_LENGTHS = frozenset({40, 64, 128})
HEX = re.compile(r"[0-9a-fA-F]+")
DIGEST_CONTEXT = re.compile(
    r"(?i)sha-?(?:1|256|384|512)|hexdigest|digest|checksum|fingerprint|content[_-]?hash"
    r"|\w*_hash\b|\bhash\b|\bcommit\b"
)
CREDENTIAL_CONTEXT = re.compile(
    r"(?i)secret|token|passw(?:or)?d|api[_-]?key|private[_-]?key|credential|bearer|authori[sz]ation"
)
CONTEXT_LINES_ABOVE = 2


def is_named_digest(secret: str, plugin: Any, context: Any) -> bool:
    """True for a Hex High Entropy finding that is a named digest; detect-secrets drops it."""
    if type(plugin).__name__ != "HexHighEntropyString":
        return False
    if len(secret) not in DIGEST_LENGTHS or not HEX.fullmatch(secret):
        return False
    lines = list(getattr(context, "lines", []) or [])
    index = int(getattr(context, "target_index", len(lines) - 1))
    if not lines or not 0 <= index < len(lines):
        return False
    if CREDENTIAL_CONTEXT.search(lines[index]):
        return False
    window = lines[max(0, index - CONTEXT_LINES_ABOVE) : index + 1]
    return any(DIGEST_CONTEXT.search(line) for line in window)
