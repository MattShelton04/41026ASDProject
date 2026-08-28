"""Stable development-workflow configuration shared by parsing and execution."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.dev.yml")
PROFILES = ("release-0",)
APPLICATION_SERVICES = (
    "shared-frontend",
    "shared-ai-mode",
    "f1-db-api",
    "f1-db-loader",
    "f1-backend",
    "f1-runner",
    "f1-frontend",
)
BUILD_SERVICES = APPLICATION_SERVICES
PRODUCTION_BUILD_SERVICES = APPLICATION_SERVICES
DEFAULT_PROJECT_NAME = "ps-dev"
RUNTIME_DIRECTORY = REPOSITORY_ROOT / ".propertyscope-runtime"
OFFLINE_OPENAI_CREDENTIAL = "offline-local-development-only"
SUPPORTED_LLM_PROVIDERS = frozenset({"gemini", "openai"})
PROPERTYSCOPE_API_URL = "http://127.0.0.1:5200/api/data-platform/v1"
JOB_PROFILE_DIRECTORY = REPOSITORY_ROOT / "student-1" / "config" / "job-profiles"
COLLECTION_JOBS = (
    "fixture-property",
    "schools-master",
    "bocsar-crime",
    "gnaf-nsw",
    "psi-sales",
)
TERMINAL_COLLECTION_STATES = frozenset({"succeeded", "failed", "cancelled"})
HOST_PORTS = {
    "shared-frontend": ("PROPERTYSCOPE_SHARED_PORT", 5100),
    "shared-ai-mode": ("AI_MODE_PORT", 5005),
    "f1-frontend": ("PROPERTYSCOPE_PORT", 5200),
}
UI_FIXTURE_SCENARIOS = (
    "populated",
    "empty",
    "slow",
    "error",
    "partial",
    "long-content",
    "large",
    "validation-error",
)
DEFAULT_UI_FIXTURE_PORT = 5300
PSI_YEARLY_URL = "https://www.valuergeneral.nsw.gov.au/__psi/yearly/{partition}.zip"
PSI_WEEKLY_URL = "https://www.valuergeneral.nsw.gov.au/__psi/weekly/{partition}.zip"
