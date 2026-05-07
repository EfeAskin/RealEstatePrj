from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import database as db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/home", response_class=HTMLResponse)
async def home(request: Request):
    # --- AKŞAM GERÇEK LİNKİ ALINCA BURAYI AÇ ---
    # villas_from_db = db.get_villas_from_db()
    # ------------------------------------------
    
    # --- ŞİMDİLİK BURASI ÇALIŞIYOR (500 Hatası Almamak İçin) ---
    villas_from_db = None 
    # ---------------------------------------------------------
    
    current_villas = {str(v['id']): v for v in villas_from_db} if villas_from_db else db.villas
    
    popular_ids = ["1", "3", "5", "6", "8", "9"]
    popular_villas = [current_villas[vid] for vid in popular_ids if vid in current_villas]
    
    return templates.TemplateResponse(request, "home.html", {
        "villas": popular_villas, 
        "role": db.current_user_role, 
        "page_id": "home"
    })

@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    # --- AKŞAM BURAYI AÇ ---
    # villas_from_db = db.get_villas_from_db()
    villas_from_db = None # Şimdilik devre dışı
    
    display_villas = villas_from_db if villas_from_db else list(db.villas.values())
    
    return templates.TemplateResponse(request, "search.html", {
        "villas": display_villas[:12], 
        "role": db.current_user_role, 
        "page_id": "search"
    })

@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse(request, "about.html", {
        "role": db.current_user_role, 
        "page_id": "about"
    })

@router.get("/aichat", response_class=HTMLResponse)
async def aichat_page(request: Request):
    return templates.TemplateResponse(request, "search.html", {
        "villas": [], 
        "role": db.current_user_role, 
        "page_id": "aichat"
    })

@router.get("/villa/{villa_id}", response_class=HTMLResponse)
async def villa_detail(request: Request, villa_id: str):
    # --- AKŞAM BURAYI AÇ ---
    # villas_from_db = db.get_villas_from_db()
    villas_from_db = None # Şimdilik devre dışı
    
    villa = None
    if villas_from_db:
        villa = next((v for v in villas_from_db if str(v['id']) == villa_id), None)
    
    if not villa:
        villa = db.villas.get(villa_id)
        
    if not villa: 
        return RedirectResponse(url="/home")
        
    return templates.TemplateResponse(request, "desktop1.html", {
        "villa": villa, 
        "role": db.current_user_role, 
        "page_id": "search"
    })