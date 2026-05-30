"""Conversational property-search assistant (the 'AI Chat' nav item).

This is intentionally NOT a free-form ChatGPT. The user describes what they want
in natural language ("apartment in Famagusta, max 700 USD"); we run the existing
4-stage semantic pipeline (query_pipeline.semantic_search), then GPT writes ONE
short framing sentence and we render the actual matching listings as cards.

GET  /aichat        -> the chat page
POST /api/ai-chat   -> {message} -> {reply, properties[], filters, count, mode}

Everything degrades gracefully when no OpenAI key is set: the pipeline falls back
to keyword/filter matching and the reply falls back to a templated sentence.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from psycopg2.extras import Json, RealDictCursor

import database as db
from db.connection import get_db_connection
from services import ai_config, openai_client, query_pipeline
from routers.property_filter import process_property_data

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# How many listings to surface per chat turn.
CHAT_TOP_K = 12
# Cap how much history we replay on load (keeps the page light for heavy users).
HISTORY_LIMIT = 200


# --------------------------------------------------------------- conversations


def _title_from(message: str) -> str:
    """A short thread title derived from the first user message."""
    t = " ".join((message or "").split())
    return (t[:48] + "…") if len(t) > 48 else (t or "New chat")


def _list_conversations(user_id):
    """This user's threads, newest-first: [{id, title, updated_at}]."""
    if not user_id:
        return []
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT conversation_id, COALESCE(NULLIF(title, ''), 'New chat') AS title, "
            "to_char(updated_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS updated_at "
            "FROM ai_conversations WHERE user_id = %s ORDER BY updated_at DESC",
            (user_id,),
        )
        rows = cur.fetchall()
        cur.close()
        return [{"id": str(r["conversation_id"]), "title": r["title"],
                 "updated_at": r["updated_at"]} for r in rows]
    except Exception as e:
        print(f"[aichat] list_conversations failed: {e}")
        return []
    finally:
        conn.close()


def _create_conversation(user_id, title):
    """Create a thread and return its id (str), or None."""
    if not user_id:
        return None
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ai_conversations (user_id, title) VALUES (%s, %s) "
            "RETURNING conversation_id",
            (user_id, title),
        )
        cid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return str(cid)
    except Exception as e:
        print(f"[aichat] create_conversation failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        conn.close()


def _owns_conversation(user_id, conversation_id):
    if not user_id or not conversation_id:
        return False
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM ai_conversations WHERE conversation_id = %s AND user_id = %s",
            (conversation_id, user_id),
        )
        ok = cur.fetchone() is not None
        cur.close()
        return ok
    except Exception as e:
        print(f"[aichat] owns_conversation failed: {e}")
        return False
    finally:
        conn.close()


def _save_message(user_id, conversation_id, role, message, properties=None):
    """Persist one turn into a thread and bump the thread's updated_at."""
    if not user_id or not conversation_id or not message:
        return
    conn = get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ai_chat_messages (user_id, conversation_id, role, message, properties_json) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, conversation_id, role, message, Json(properties) if properties else None),
        )
        cur.execute(
            "UPDATE ai_conversations SET updated_at = now() WHERE conversation_id = %s",
            (conversation_id,),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"[aichat] save_message failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def _load_history(user_id, conversation_id, limit=HISTORY_LIMIT):
    """Return a thread's turns oldest-first: [{role, message, properties}]."""
    if not user_id or not conversation_id:
        return []
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT role, message, properties_json FROM ai_chat_messages "
            "WHERE user_id = %s AND conversation_id = %s "
            "ORDER BY created_at ASC, message_id ASC LIMIT %s",
            (user_id, conversation_id, limit),
        )
        rows = cur.fetchall()
        cur.close()
        return [{"role": r["role"], "message": r["message"],
                 "properties": r["properties_json"] or []} for r in rows]
    except Exception as e:
        print(f"[aichat] load_history failed: {e}")
        return []
    finally:
        conn.close()


def _delete_conversation(user_id, conversation_id):
    if not user_id or not conversation_id:
        return False
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM ai_chat_messages WHERE user_id = %s AND conversation_id = %s",
            (user_id, conversation_id),
        )
        cur.execute(
            "DELETE FROM ai_conversations WHERE user_id = %s AND conversation_id = %s",
            (user_id, conversation_id),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[aichat] delete_conversation failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


def _slim_card(prop: dict) -> dict:
    """Reduce a full property row to just what the chat result card needs."""
    p = process_property_data(dict(prop)) or {}
    return {
        "id": p.get("id"),
        "name": p.get("name") or p.get("title") or "Listing",
        "image": p.get("image") or "htmlfotos/default.jpg",
        "formatted_price": p.get("formatted_price"),
        "currency_symbol": p.get("currency_symbol"),
        "display_type": p.get("display_type"),
        "is_sale": p.get("is_sale", False),
        "room_count": p.get("room_count"),
        "bath_count": p.get("bath_count"),
        "location": p.get("location") or p.get("city") or "N/A",
    }


def _fallback_reply(message: str, count: int) -> str:
    """Templated sentence used when GPT is off/unavailable — keeps the UX intact."""
    if count == 0:
        return ("I couldn't find any listings matching that. Try widening your budget "
                "or location and ask me again.")
    return f"Here are {count} propert{'y' if count == 1 else 'ies'} I found based on your request:"


@router.get("/aichat", response_class=HTMLResponse)
def aichat_page(request: Request):
    user = db.get_user_from_request(request)
    role = user.get("role", "guest") if user else "guest"
    user_id = user.get("id") if user else None

    conversations = _list_conversations(user_id)
    # Open the most recent thread on load (like ChatGPT); empty -> a fresh chat.
    active_id = conversations[0]["id"] if conversations else None
    history = _load_history(user_id, active_id) if active_id else []

    return templates.TemplateResponse(request, "aichat.html", {
        "role": role,
        "user": user,
        "page_id": "aichat",
        "ai_enabled": ai_config.ai_enabled(),
        "is_logged_in": bool(user_id),
        "conversations": conversations,
        "active_id": active_id,
        "history": history,
    })


@router.post("/api/ai-chat")
def ai_chat(request: Request, body: ChatRequest):
    message = (body.message or "").strip()
    if not message:
        return JSONResponse(status_code=400, content={"error": "Empty message."})

    user = db.get_user_from_request(request)
    user_id = user.get("id") if user else None

    # Resolve the thread: reuse the one the client sent (if owned), else start a new
    # one titled from this first message. Guests get no thread (nothing persists).
    conversation_id = (body.conversation_id or "").strip() or None
    new_conversation = False
    title = None
    if user_id:
        if not (conversation_id and _owns_conversation(user_id, conversation_id)):
            title = _title_from(message)
            conversation_id = _create_conversation(user_id, title)
            new_conversation = True

    # Persist the user's turn first, so history is correct even if the pipeline errors.
    _save_message(user_id, conversation_id, "user", message)

    # min_results=1: only broaden the search when *nothing* matched the user's hard
    # constraints, so we respect budget/location instead of padding with off-target rows.
    out = query_pipeline.semantic_search(message, top_k=CHAT_TOP_K, user_id=user_id,
                                         min_results=1)
    rows = out.get("results", [])
    cards = [_slim_card(r) for r in rows]
    count = len(cards)
    dropped = out.get("dropped", [])

    reply = None
    if ai_config.ai_enabled():
        reply = openai_client.chat_reply(
            message,
            out.get("filters", {}),
            count,
            sample_titles=[c["name"] for c in cards],
            dropped=dropped,
        )
    if not reply:
        reply = _fallback_reply(message, count)

    # Persist the assistant's reply (with the cards it surfaced) for replay on reload.
    _save_message(user_id, conversation_id, "assistant", reply, properties=cards)

    return JSONResponse({
        "reply": reply,
        "count": count,
        "mode": out.get("mode"),
        "ai_enabled": ai_config.ai_enabled(),
        "filters": {k: v for k, v in (out.get("filters") or {}).items() if v not in (None, "")},
        "properties": cards,
        "conversation_id": conversation_id,
        "title": title,
        "new_conversation": new_conversation,
    })


# --------------------------------------------------------------- thread endpoints

@router.get("/api/ai-chat/conversations")
def ai_chat_conversations(request: Request):
    """Sidebar list of the user's threads (newest-first)."""
    user = db.get_user_from_request(request)
    user_id = user.get("id") if user else None
    return JSONResponse({"conversations": _list_conversations(user_id)})


@router.get("/api/ai-chat/conversation/{conversation_id}")
def ai_chat_conversation(conversation_id: str, request: Request):
    """Messages of one thread, for switching threads without a full reload."""
    user = db.get_user_from_request(request)
    user_id = user.get("id") if user else None
    if not user_id or not _owns_conversation(user_id, conversation_id):
        return JSONResponse(status_code=404, content={"error": "Conversation not found."})
    return JSONResponse({
        "conversation_id": conversation_id,
        "messages": _load_history(user_id, conversation_id),
    })


@router.delete("/api/ai-chat/conversation/{conversation_id}")
def ai_chat_delete_conversation(conversation_id: str, request: Request):
    """Delete one thread and all its messages."""
    user = db.get_user_from_request(request)
    user_id = user.get("id") if user else None
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "You must be logged in."})
    if not _owns_conversation(user_id, conversation_id):
        return JSONResponse(status_code=404, content={"error": "Conversation not found."})
    ok = _delete_conversation(user_id, conversation_id)
    return JSONResponse({"success": ok})
