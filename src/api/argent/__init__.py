
from fastapi import APIRouter

from src.api.argent import classifier, close, context, cost, holds_routes, outage, pair, precedence, reach, rollout, status, work_items, writeback
from src.core.argent import lifecycle

lifecycle.install()

router = APIRouter(prefix="/argent")
router.include_router(holds_routes.router)
router.include_router(status.router)
router.include_router(work_items.router)
router.include_router(precedence.router)
router.include_router(context.router)
router.include_router(rollout.router)
router.include_router(classifier.router)
router.include_router(cost.router)
router.include_router(outage.router)
router.include_router(writeback.router)
router.include_router(reach.router)
router.include_router(pair.router)
router.include_router(close.router)
