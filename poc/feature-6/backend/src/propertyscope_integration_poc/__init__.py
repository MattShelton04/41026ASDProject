"""Feature 6 integration proof-of-concept public surface."""

from .feature1_client import (
    AcceptedRelease,
    Feature1Client,
    Feature1ContractError,
    Feature1HttpError,
)
from .publication_importer import (
    JsonSchemaRecordValidator,
    PublicationConflictError,
    PublicationImporter,
    PublicationImportError,
    PublicationReceipt,
    PublicationRequest,
    PublicationStore,
    StoredPublication,
    contract_friction_notes,
)

__all__ = [
    "AcceptedRelease",
    "Feature1Client",
    "Feature1ContractError",
    "Feature1HttpError",
    "JsonSchemaRecordValidator",
    "PublicationConflictError",
    "PublicationImportError",
    "PublicationImporter",
    "PublicationReceipt",
    "PublicationRequest",
    "PublicationStore",
    "StoredPublication",
    "contract_friction_notes",
]
