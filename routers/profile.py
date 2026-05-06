from fastapi import APIRouter, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import database as db

router = APIRouter(prefix="/profile")
templates = Jinja2Templates(directory="templates")

# --- YARDIMCI FONKSİYON (Admin Kontrolü İçin) ---
def get_admin_status():
    """Kullanıcının rolü admin ise True döner"""
    return db.current_user_role == "admin"

# --- GENEL / ORTAK ROTALAR ---

@router.get("/personal-info", response_class=HTMLResponse)
async def personal_info(request: Request):
    """Kişisel Bilgiler Sayfası"""
    user_email = db.current_user_email 
    user_data = db.users.get(user_email, db.current_user_data)
    
    return templates.TemplateResponse(request, "personal_info.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "email": user_email,
        "phone": user_data.get("phone", ""),
        "gender": user_data.get("gender", ""),
        # --- AGENT ÖZEL BİLGİLERİ ---
        "iban": user_data.get("iban", ""),
        "id_no": user_data.get("id_no", ""),
        "company_name": user_data.get("company_name", ""),
        "p_page": "info"
    })

@router.post("/update-info")
async def update_info(
    request: Request, 
    first_name: str = Form(...), 
    last_name: str = Form(...),
    phone: str = Form(None),
    gender: str = Form(None),
    iban: str = Form(None),
    id_no: str = Form(None),
    company_name: str = Form(None),
    new_password: str = Form(None)
):
    """Kişisel Bilgileri db.users içinde günceller"""
    user_email = db.current_user_email
    
    if user_email in db.users:
        db.users[user_email]["first_name"] = first_name
        db.users[user_email]["last_name"] = last_name
        db.users[user_email]["phone"] = phone
        db.users[user_email]["gender"] = gender
        
        if db.current_user_role == "agent":
            db.users[user_email]["iban"] = iban
            db.users[user_email]["id_no"] = id_no
            db.users[user_email]["company_name"] = company_name
        
        if new_password and new_password.strip() != "":
            db.users[user_email]["password"] = db.hash_password(new_password)
        
        db.current_user_data = db.users[user_email]
        
    return RedirectResponse(url="/profile/personal-info", status_code=303)

@router.get("/messages", response_class=HTMLResponse)
async def my_messages(request: Request):
    """Mesajlar Sayfası"""
    return templates.TemplateResponse(request, "messages.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": db.current_user_data.get("first_name", ""),
        "last_name": db.current_user_data.get("last_name", ""),
        "p_page": "messages"
    })

@router.get("/favourites", response_class=HTMLResponse)
async def my_favourites(request: Request):
    """Favoriler Sayfası"""
    return templates.TemplateResponse(request, "favourites.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": db.current_user_data.get("first_name", ""),
        "last_name": db.current_user_data.get("last_name", ""),
        "p_page": "favourites"
    })

# --- ROL DEĞİŞTİRME ROTALARI ---

@router.get("/switch-to-agent")
async def switch_to_agent(request: Request):
    user_email = db.current_user_email
    user_data = db.users.get(user_email, {})

    if user_data.get("iban") and user_data.get("id_no"):
        db.current_user_role = "agent"
        db.users[user_email]["role"] = "agent"
        db.current_user_data = db.users[user_email]
        return RedirectResponse(url="/profile/personal-info", status_code=status.HTTP_303_SEE_OTHER)
    
    return templates.TemplateResponse(request, "choose_role.html", {
        "role": db.current_user_role, 
        "is_admin": get_admin_status()
    })

@router.post("/upgrade-to-agent")
async def upgrade_to_agent(
    request: Request,
    iban: str = Form(...),
    id_no: str = Form(...),
    company_name: str = Form(None)
):
    user_email = db.current_user_email
    db.current_user_role = "agent"
    
    if user_email in db.users:
        db.users[user_email]["role"] = "agent"
        db.users[user_email]["iban"] = iban
        db.users[user_email]["id_no"] = id_no
        db.users[user_email]["company_name"] = company_name
        db.current_user_data = db.users[user_email]
    
    return RedirectResponse(url="/profile/personal-info", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/switch-to-user")
async def switch_to_user():
    user_email = db.current_user_email
    db.current_user_role = "user"
    
    if user_email in db.users:
        db.users[user_email]["role"] = "user"
        db.current_user_data = db.users[user_email]
        
    return RedirectResponse(url="/profile/personal-info", status_code=status.HTTP_303_SEE_OTHER)

# --- USER ÖZEL ROTALARI ---

@router.get("/transactions", response_class=HTMLResponse)
async def my_transactions(request: Request):
    return templates.TemplateResponse(request, "transactions.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": db.current_user_data.get("first_name", ""),
        "last_name": db.current_user_data.get("last_name", ""),
        "p_page": "transactions"
    })

# --- AGENT ÖZEL ROTALARI ---

@router.get("/properties", response_class=HTMLResponse)
async def agent_properties(request: Request):
    return templates.TemplateResponse(request, "properties.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": db.current_user_data.get("first_name", ""),
        "last_name": db.current_user_data.get("last_name", ""),
        "p_page": "properties"
    })

@router.get("/requests", response_class=HTMLResponse)
async def agent_requests(request: Request):
    return templates.TemplateResponse(request, "requests.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": db.current_user_data.get("first_name", ""),
        "last_name": db.current_user_data.get("last_name", ""),
        "p_page": "requests"
    })

@router.get("/payment", response_class=HTMLResponse)
async def agent_payment_page(request: Request):
    return templates.TemplateResponse(request, "payment.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": db.current_user_data.get("first_name", ""),
        "last_name": db.current_user_data.get("last_name", ""),
        "p_page": "payment"
    })

# --- ADMIN ÖZEL ROTALARI ---

@router.get("/all-properties", response_class=HTMLResponse)
async def admin_all_properties(request: Request):
    return templates.TemplateResponse(request, "all_properties.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "all-properties",
        "first_name": db.current_user_data.get("first_name", ""), 
        "last_name": db.current_user_data.get("last_name", "")
    })

@router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request):
    return templates.TemplateResponse(request, "users.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "users",
        "first_name": db.current_user_data.get("first_name", ""), 
        "last_name": db.current_user_data.get("last_name", "")
    })

@router.get("/approving", response_class=HTMLResponse)
async def admin_approving(request: Request):
    return templates.TemplateResponse(request, "approving.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "approving",
        "first_name": db.current_user_data.get("first_name", ""), 
        "last_name": db.current_user_data.get("last_name", "")
    })

@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "dashboard",
        "first_name": db.current_user_data.get("first_name", ""), 
        "last_name": db.current_user_data.get("last_name", "")
    })

@router.get("/system-logs", response_class=HTMLResponse)
async def admin_system_logs(request: Request):
    return templates.TemplateResponse(request, "system_logs.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "system-logs",
        "first_name": db.current_user_data.get("first_name", ""), 
        "last_name": db.current_user_data.get("last_name", "")
    })

@router.get("/sales-logs", response_class=HTMLResponse)
async def admin_sales_logs(request: Request):
    return templates.TemplateResponse(request, "sales_logs.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "sales-logs",
        "first_name": db.current_user_data.get("first_name", ""), 
        "last_name": db.current_user_data.get("last_name", "")
    })

# --- FORM VE HESAPLAMA İŞLEMLERİ ---

@router.post("/calculate-booking")
async def calculate_booking(
    request: Request, 
    villa_id: str = Form(...), 
    check_in: str = Form(...), 
    check_out: str = Form(...), 
    nights: int = Form(...), 
    guest_info: str = Form(...)
):
    villa = db.villas.get(villa_id)
    if not villa:
        return {"error": "Villa bulunamadı"}
        
    daily_price = villa["monthly_price"] / 30
    total_price = round(daily_price * nights, 2)
    
    return templates.TemplateResponse(request, "payment.html", {
        "villa": villa, 
        "check_in": check_in, 
        "check_out": check_out, 
        "nights": nights, 
        "total_price": total_price, 
        "guest_info": guest_info, 
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": db.current_user_data.get("first_name", ""),
        "last_name": db.current_user_data.get("last_name", ""),
        "p_page": "payment"
    })