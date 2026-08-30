"""Stable development-workflow configuration shared by parsing and execution."""

import json
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    "docker-compose.yml",
    "deployment/enabled-features.compose.yml",
    "docker-compose.dev.yml",
)
PRODUCTION_COMPOSE_FILES = COMPOSE_FILES[:-1]
PROFILES = ("release-0",)
SHARED_APPLICATION_SERVICES = (
    "shared-frontend",
    "shared-ai-mode",
)
_ENABLED_SERVICES_PATH = REPOSITORY_ROOT / "deployment" / "enabled-services.v1.json"
_ENABLED_FEATURES_PATH = REPOSITORY_ROOT / "deployment" / "enabled-features.v1.json"


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"generated deployment input must be an object: {path}")
    return value


def _enabled_feature_services(field: str = "build_services") -> tuple[str, ...]:
    values = _json_object(_ENABLED_SERVICES_PATH).get(field)
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise RuntimeError(f"generated enabled {field} are invalid")
    if len(values) != len(set(values)):
        raise RuntimeError(f"generated enabled {field} contain duplicates")
    return tuple(values)


APPLICATION_SERVICES = (*SHARED_APPLICATION_SERVICES, *_enabled_feature_services())
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
HOST_PORTS: dict[str, tuple[str, int]] = {
    "shared-frontend": ("PROPERTYSCOPE_SHARED_PORT", 5100),
    "shared-ai-mode": ("AI_MODE_PORT", 5005),
}
for _feature in _json_object(_ENABLED_FEATURES_PATH).get("features", []):
    if not isinstance(_feature, dict) or not isinstance(_feature.get("frontend"), dict):
        continue
    _frontend = _feature["frontend"]
    _service = _frontend.get("service")
    _variable = _frontend.get("host_port_variable")
    _default = _frontend.get("host_port_default")
    if isinstance(_service, str) and isinstance(_variable, str) and isinstance(_default, int):
        HOST_PORTS[_service] = (_variable, _default)
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
