"""G-NAF archive member validation and deterministic selected-geocode policy."""

from __future__ import annotations

from dataclasses import dataclass
from zipfile import ZipFile

REQUIRED_MEMBER_SUFFIXES = (
    "NSW_ADDRESS_DETAIL_PSV.PSV",
    "NSW_DEFAULT_GEOCODE_PSV.PSV",
    "NSW_LOCALITY_PSV.PSV",
    "NSW_STREET_LOCALITY_PSV.PSV",
)
GEOCODE_PREFERENCE = {"PC": 0, "PAP": 1, "GAP": 2, "GNAF": 3, "LOCALITY": 20}


@dataclass(frozen=True, slots=True)
class GnafMemberManifest:
    members: tuple[str, ...]
    coordinate_reference_system: str


def inspect_gnaf_archive(archive: ZipFile, *, maximum_members: int = 1000) -> GnafMemberManifest:
    names = tuple(sorted(info.filename for info in archive.infolist() if not info.is_dir()))
    if len(names) > maximum_members:
        raise ValueError("G-NAF archive exceeds registered member limit")
    for name in names:
        if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
            raise ValueError("G-NAF archive contains an unsafe member path")
    for suffix in REQUIRED_MEMBER_SUFFIXES:
        matches = [name for name in names if name.upper().endswith(suffix)]
        if len(matches) != 1:
            raise ValueError(f"G-NAF archive requires exactly one {suffix} member")
    upper_names = "\n".join(names).upper()
    crs = (
        "GDA2020" if "GDA2020" in upper_names else "GDA94" if "GDA94" in upper_names else "UNKNOWN"
    )
    if crs == "UNKNOWN":
        raise ValueError("G-NAF archive coordinate reference system is not declared")
    return GnafMemberManifest(names, crs)


def select_geocode(candidates: tuple[dict[str, str], ...]) -> dict[str, str] | None:
    """Choose one geocode by registered type preference and stable source identifier."""
    valid = [candidate for candidate in candidates if _coordinate(candidate)]
    if not valid:
        return None
    return min(
        valid,
        key=lambda item: (
            GEOCODE_PREFERENCE.get(item.get("GEOCODE_TYPE_CODE", "").upper(), 100),
            item.get("GEOCODE_PID", ""),
        ),
    )


def _coordinate(candidate: dict[str, str]) -> bool:
    try:
        latitude = float(candidate["LATITUDE"])
        longitude = float(candidate["LONGITUDE"])
        return -45 <= latitude <= -9 and 110 <= longitude <= 155
    except (KeyError, ValueError):
        return False
