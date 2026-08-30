"""Feature 6 integration proof-of-concept public surface."""

from .ai_client import AiModeClient, AiModeUnavailableError
from .app import create_app
from .configuration import Settings
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
from .store_client import StoreHttpClient, StoreHttpError

__all__ = [
    "AcceptedRelease",
    "AiModeClient",
    "AiModeUnavailableError",
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
    "Settings",
    "StoreHttpClient",
    "StoreHttpError",
    "StoredPublication",
    "contract_friction_notes",
    "create_app",
]
