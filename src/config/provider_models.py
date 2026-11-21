
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List

from src.config.config_file import require_config_file
from src.core import config_writer
from src.config.providers import _DEFAULT_PROVIDER_MODELS


def _edit_models(config_path: Path, change: Callable[[List[str]], None]) -> List[str]:
    require_config_file(config_path)

    def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
        providers_data = data.get("providers") or {}
        models = list(providers_data.get("models", _DEFAULT_PROVIDER_MODELS))
        change(models)
        providers_data["models"] = models
        data["providers"] = providers_data
        return data

    outcome = config_writer.commit(config_path, mutate)
    return list(outcome.data["providers"]["models"])


def add(config_path: Path, model: str) -> List[str]:

    def change(models: List[str]) -> None:
        if model in models:
            raise ValueError(f"Model '{model}' already exists")
        models.append(model)

    return _edit_models(config_path, change)


def remove(config_path: Path, model: str) -> List[str]:

    def change(models: List[str]) -> None:
        if model not in models:
            raise ValueError(f"Model '{model}' not found")
        models.remove(model)

    return _edit_models(config_path, change)
