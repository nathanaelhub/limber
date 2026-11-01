"""
Exercise and program catalog from config.yaml (FR-005).

The configuration is the only source of pre-built programs; nothing is copied into the
database (research D1). Custom programs are built from exercise keys that exist here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .models import Program, ProgramValidationError
from .store import REPO_ROOT

CUSTOM_ID = "custom"
CUSTOM_NAME = "Custom"


@dataclass
class Catalog:
    exercises: Dict[str, Dict] = field(default_factory=dict)   # key -> display_name, side, up_angle, down_angle, target_reps, description
    programs: Dict[str, Program] = field(default_factory=dict)


_CACHE: Dict[str, Catalog] = {}


def _path(config_path: Optional[Path]) -> Path:
    return Path(config_path) if config_path else REPO_ROOT / "config.yaml"


def load_catalog(config_path: Optional[Path] = None) -> Catalog:
    """Parse the configuration once per path and cache it."""
    path = _path(config_path)
    key = str(path)
    if key in _CACHE:
        return _CACHE[key]
    catalog = Catalog()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    for ex_key, ex in (data.get("exercises") or {}).items():
        catalog.exercises[ex_key] = {
            "display_name": str(ex.get("display_name", ex_key)),
            "side": ex.get("side", "left"),
            "up_angle": float(ex.get("up_angle", 0.0)),
            "down_angle": float(ex.get("down_angle", 0.0)),
            "target_reps": int(ex.get("target_reps", 10)),
            "description": str(ex.get("description") or ""),
        }
    for prog_id, prog in (data.get("programs") or {}).items():
        keys = [str(k) for k in (prog.get("exercises") or [])]
        catalog.programs[prog_id] = Program(
            id=prog_id, name=str(prog.get("name", prog_id)), description=str(prog.get("description") or ""),
            exercise_keys=keys, exercise_names=[_name(catalog, k) for k in keys],
        )
    _CACHE[key] = catalog
    return catalog


def _name(catalog: Catalog, key: str) -> str:
    entry = catalog.exercises.get(key)
    return entry["display_name"] if entry else key


def list_programs(config_path: Optional[Path] = None) -> List[Program]:
    return list(load_catalog(config_path).programs.values())


def get_program(program_id: str, config_path: Optional[Path] = None) -> Optional[Program]:
    return load_catalog(config_path).programs.get(program_id)


def exercise_name(key: str, config_path: Optional[Path] = None) -> str:
    """Display name for a key; the key itself when the configuration no longer has it."""
    return _name(load_catalog(config_path), key)


def validate_exercise_keys(keys: List[str], config_path: Optional[Path] = None) -> List[str]:
    """Return the keys unchanged when every one exists in the configuration."""
    keys = [str(k).strip() for k in keys if str(k).strip()]
    if not keys:
        raise ProgramValidationError("a program needs at least one exercise")
    known = load_catalog(config_path).exercises
    unknown = [k for k in keys if k not in known]
    if unknown:
        raise ProgramValidationError(f"Unknown exercise keys: {', '.join(unknown)}")
    return keys


def custom_program(keys: List[str], config_path: Optional[Path] = None) -> Program:
    keys = validate_exercise_keys(keys, config_path)
    return Program(CUSTOM_ID, CUSTOM_NAME, "", keys, [exercise_name(k, config_path) for k in keys])
