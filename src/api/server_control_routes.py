
import structlog
from fastapi import APIRouter, Depends, Request
from src.api.auth import require_auth
from src.models import SuccessResponse

logger = structlog.get_logger()
router = APIRouter()


@router.post("/shutdown", response_model=SuccessResponse, dependencies=[Depends(require_auth)])
async def shutdown_server(request: Request):
    """
    Gracefully shut down the server.
    Used by menu bar app to restart the server.

    Returns:
        Success response

    Note: Server will exit after sending response
    """
    import os
    import signal
    import asyncio

    logger.info("api_shutdown_request")

    async def delayed_shutdown():
        await asyncio.sleep(0.5)
        logger.info("initiating_graceful_shutdown")
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(delayed_shutdown())
    return SuccessResponse(message="Server shutdown initiated")
