from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import database as db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/home", response_class=HTMLResponse)
async def home(request: Request):
    popular_ids = ["1", "3", "5", "6", "8", "9"]
    popular_villas = [db.villas[vid] for vid in popular_ids if vid in db.villas]
    return templates.TemplateResponse(request, "home.html", {"villas": popular_villas, "role": db.current_user_role, "page_id": "home"})

@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return templates.TemplateResponse(request, "search.html", {"villas": list(db.villas.values())[:12], "role": db.current_user_role, "page_id": "search"})

@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse(request, "about.html", {"role": db.current_user_role, "page_id": "about"})

@router.get("/aichat", response_class=HTMLResponse)
async def aichat_page(request: Request):
    return templates.TemplateResponse(request, "search.html", {"villas": [], "role": db.current_user_role, "page_id": "aichat"})

@router.get("/villa/{villa_id}", response_class=HTMLResponse)
async def villa_detail(request: Request, villa_id: str):
    villa = db.villas.get(villa_id)
    if not villa: return RedirectResponse(url="/home")
    return templates.TemplateResponse(request, "desktop1.html", {"villa": villa, "role": db.current_user_role, "page_id": "search"})