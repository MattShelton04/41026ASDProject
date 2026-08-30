"""Domain-neutral, bounded consumer protocol for published release artifacts."""

from .consumer import (
    ArtifactAccessPolicy,
    AtomicImportSink,
    ConsumerProtocolError,
    ManifestValidator,
    Record,
    RecordValidator,
    consume_publication,
    publication_headers,
)
from .contracts import (
    CorrelationContext,
    ImportEvidence,
    ImportReceipt,
    ManifestBinding,
    PublicationRequest,
    ReceiptError,
    ReleaseIdentity,
    immutable_identity,
)

__all__ = [
    "ArtifactAccessPolicy",
    "AtomicImportSink",
    "ConsumerProtocolError",
    "CorrelationContext",
    "ImportEvidence",
    "ImportReceipt",
    "ManifestBinding",
    "ManifestValidator",
    "PublicationRequest",
    "ReceiptError",
    "Record",
    "RecordValidator",
    "ReleaseIdentity",
    "consume_publication",
    "immutable_identity",
    "publication_headers",
]
