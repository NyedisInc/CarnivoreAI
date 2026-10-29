
import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from src.api.auth import require_auth
from src.config import settings
from src.models import (
    AddProviderModelRequest,
    LocalModelsResponse,
    ProviderModelsResponse,
    describe_model_id_rejection,
    is_valid_model_id,
)
from src.api.error_response import api_error, soft_failure

logger = structlog.get_logger()
local_models_router = APIRouter()
router = APIRouter()


@local_models_router.get(
    "/providers/local/models",
    response_model=LocalModelsResponse,
    dependencies=[Depends(require_auth)],
)
async def list_local_models():
    """List the chat models an LM Studio server is serving.

    Description: ALWAYS answers 200. A box that is off is a state the
      picker renders, not an API failure - see LocalModelsResponse.

      The address comes from ``providers.local_host`` in config.json and
      there is deliberately NO endpoint that sets it. This handler makes an
      outbound request to whatever that value names, so a setter would be
      an SSRF surface reachable with one authenticated POST. Editing
      config.json is already box-level access; a route is not.
    Output: LocalModelsResponse.
    """
    from src.core.local_models import fetch_local_models, to_payload

    try:
        host = settings.load_auth_config().providers.local_host
    except Exception as exc:  # noqa: BLE001
        return LocalModelsResponse(
            state="not-configured",
            detail=soft_failure("provider_config_unreadable", exc, step="read_local_host"),
        )

    result = await run_in_threadpool(fetch_local_models, host)
    return LocalModelsResponse(**to_payload(result))




@router.get(
    "/providers",
    response_model=ProviderModelsResponse,
    dependencies=[Depends(require_auth)],
)
async def list_provider_models():
    """List the persisted OpenRouter model catalog for the provider modal."""
    return ProviderModelsResponse(models=settings.get_provider_models())


@router.post(
    "/providers/models",
    response_model=ProviderModelsResponse,
    dependencies=[Depends(require_auth)],
)
async def add_provider_model(body: AddProviderModelRequest):
    """Add an OpenRouter model id to the provider catalog.

    Raises:
        HTTPException(400): model id doesn't match ``MODEL_ID_PATTERN`` - the
            detail names the specific reason, not a generic pattern dump.
        HTTPException(409): model id already present.
    """
    if not is_valid_model_id(body.model):
        raise HTTPException(
            status_code=400,
            detail=describe_model_id_rejection(body.model),
        )

    try:
        models = settings.add_provider_model(body.model)
    except ValueError as e:
        raise api_error(409, "conflict", e, step="add_provider_model") from e

    return ProviderModelsResponse(models=models)


@router.delete(
    "/providers/models/{model:path}",
    response_model=ProviderModelsResponse,
    dependencies=[Depends(require_auth)],
)
async def remove_provider_model(model: str):
    """Remove an OpenRouter model id from the provider catalog.

    ``{model:path}`` (not the default ``{model}``) because model ids
    contain ``/`` (e.g. ``openai/gpt-5.6-sol``) - the plain converter
    would truncate at the first slash.

    Raises:
        HTTPException(404): model id isn't in the catalog.
    """
    try:
        models = settings.remove_provider_model(model)
    except ValueError as e:
        raise api_error(404, "not_found", e, step="remove_provider_model") from e

    return ProviderModelsResponse(models=models)
