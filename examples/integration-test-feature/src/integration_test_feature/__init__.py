"""Generic feature slice used only for shared-platform integration evidence."""

from integration_test_feature.backend import create_backend_app
from integration_test_feature.database import IntegrationRecordStore, create_database_app

__all__ = ["IntegrationRecordStore", "create_backend_app", "create_database_app"]
