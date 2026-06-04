"""JSON endpoints for the AI layer.

Kept separate from the main /search page so the 4-stage GPT pipeline can be
exercised (assistant, "similar listings", "recommended for you") without
destabilizing the existing search UI. All endpoints degrade gracefully when no
OpenAI key is configured.
"""
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse

import database as db
from services import ai_config, query_pipeline, recommendations

router = APIRouter()


def _current_user_id(request: Request):
    user = db.get_user_from_request(request)
    return user.get("id") if user else None


@router.get("/api/ai-search")
async def ai_search(request: Request, q: str = Query(...), top_k: int = Query(20, ge=1, le=50)):
    """Run the full pipeline: normalize -> GPT extract -> filter -> vector rerank."""
    out = query_pipeline.semantic_search(q, top_k=top_k, user_id=_current_user_id(request))
    return JSONResponse({
        "query": q,
        "mode": out["mode"],            # 'semantic' | 'filter_only' | 'error'
        "ai_enabled": ai_config.ai_enabled(),
        "filters": out["filters"],
        "count": len(out["results"]),
        "results": out["results"],
    })


@router.get("/api/recommendations")
async def recommendations_endpoint(request: Request, top_k: int = Query(10, ge=1, le=50)):
    uid = _current_user_id(request)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "Login required."})
    out = recommendations.recommend_for_user(uid, top_k=top_k)
    return JSONResponse({"basis": out["basis"], "count": len(out["results"]), "results": out["results"]})


@router.get("/api/properties/{property_id}/similar")
async def similar_endpoint(property_id: int, top_k: int = Query(8, ge=1, le=24)):
    rows = recommendations.similar_properties(property_id, top_k=top_k)
    return JSONResponse({"count": len(rows), "results": rows})
