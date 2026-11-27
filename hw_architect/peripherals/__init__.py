"""Peripheral catalog loader and helpers."""

from __future__ import annotations

from pathlib import Path

import yaml

from contracts.hw_models import PeripheralSpec

_CATALOG_PATH = Path(__file__).resolve().parent / "catalog.yaml"


def load_peripheral_catalog() -> dict[str, dict]:
    data = yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8"))
    return data.get("peripherals", {})


def make_peripheral_from_catalog(
    template_key: str,
    instance_id: str,
    *,
    manual_pins: dict[str, str] | None = None,
    overrides: dict | None = None,
) -> PeripheralSpec:
    catalog = load_peripheral_catalog()
    if template_key not in catalog:
        raise KeyError(f"Unknown peripheral template '{template_key}'")
    raw = dict(catalog[template_key])
    raw["instance_id"] = instance_id
    if manual_pins:
        raw["manual_pins"] = dict(manual_pins)
    if overrides:
        raw.update(overrides)
    return PeripheralSpec.model_validate(raw)
