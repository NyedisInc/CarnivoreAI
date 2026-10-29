
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from src.config.config_file import read_config, require_config_file
from src.config.providers import _DEFAULT_PROVIDER_MODELS


def _persisted_models(config_path: Path) -> tuple[dict, dict, List[str]]:
    data = read_config(config_path)
    providers_data = data.get("providers") or {}
    return data, providers_data, list(
        providers_data.get("models", _DEFAULT_PROVIDER_MODELS)
    )


def _write(config_path: Path, data: dict, providers_data: dict, models: List[str]) -> None:
    providers_data["models"] = models
    data["providers"] = providers_data
    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)


def add(config_path: Path, model: str) -> List[str]:
    require_config_file(config_path)
    data, providers_data, models = _persisted_models(config_path)

    if model in models:
        raise ValueError(f"Model '{model}' already exists")

    models.append(model)
    _write(config_path, data, providers_data, models)
    return models


def remove(config_path: Path, model: str) -> List[str]:
    require_config_file(config_path)
    data, providers_data, models = _persisted_models(config_path)

    if model not in models:
        raise ValueError(f"Model '{model}' not found")

    models.remove(model)
    _write(config_path, data, providers_data, models)
    return models
