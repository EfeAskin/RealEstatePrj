from fastapi import APIRouter, Request, Form, status, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import database as db
import os
import shutil

router = APIRouter(prefix="/profile")
templates = Jinja2Templates(directory="templates")

# --- YARDIMCI FONKSİYONLAR ---
def get_admin_status():
    """Kullanıcının rolü admin ise True döner"""
    return db.current_user_role == "admin"

# --- GENEL / ORTAK ROTALAR ---

@router.get("/personal-info", response_class=HTMLResponse)
async def personal_info(request: Request):
    """Kişisel Bilgiler Sayfası"""
    user_email = db.current_user_email 
    user_data = db.get_user_from_db(user_email)
    
    if not user_data:
        user_data = db.current_user_data
    
    return templates.TemplateResponse(request, "personal_info.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "email": user_email,
        "phone": user_data.get("phone", ""),
        "gender": user_data.get("gender", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
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
    new_password: str = Form(None),
    profile_image: UploadFile = File(None)
):
    """Kişisel Bilgileri ve Profil Fotoğrafını DB içinde günceller"""
    user_email = db.current_user_email
    user_data = db.get_user_from_db(user_email)
    
    filename = user_data.get("profile_image", "default_user.png")

    if profile_image and profile_image.filename:
        upload_dir = "static/htmlfotos"
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
            
        extension = os.path.splitext(profile_image.filename)[1]
        filename = f"user_{user_data['id']}{extension}"
        file_path = os.path.join(upload_dir, filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(profile_image.file, buffer)

    update_data = {
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "gender": gender,
        "iban": iban,
        "id_no": id_no,
        "company_name": company_name,
        "profile_image": filename
    }
    
    if new_password and new_password.strip() != "":
        update_data["password"] = new_password

    try:
        db.update_user_in_db(user_email, update_data)
        refreshed_user = db.get_user_from_db(user_email)
        if refreshed_user:
            db.current_user_data = refreshed_user
            
    except Exception as e:
        print(f"Update hatası: {e}")

    return RedirectResponse(url="/profile/personal-info", status_code=303)

@router.get("/messages", response_class=HTMLResponse)
async def my_messages(request: Request):
    """Mesajlar Sayfası"""
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "messages.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "messages"
    })

@router.get("/favourites", response_class=HTMLResponse)
async def my_favourites(request: Request):
    """Favoriler Sayfası"""
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "favourites.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "favourites"
    })

# --- ROL DEĞİŞTİRME ROTALARI ---

@router.get("/switch-to-agent")
async def switch_to_agent(request: Request):
    user_email = db.current_user_email
    user_data = db.get_user_from_db(user_email)

    if user_data and user_data.get("iban") and user_data.get("id_no"):
        db.current_user_role = "agent"
        db.update_user_in_db(user_email, {"role": "agent", "first_name": user_data['first_name'], "last_name": user_data['last_name']})
        db.current_user_data["role"] = "agent"
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
    user_data = db.get_user_from_db(user_email)
    db.current_user_role = "agent"
    
    update_data = {
        "role": "agent", 
        "iban": iban, 
        "id_no": id_no, 
        "company_name": company_name,
        "first_name": user_data['first_name'],
        "last_name": user_data['last_name']
    }
    
    db.update_user_in_db(user_email, update_data)
    db.current_user_data.update(update_data)
    
    return RedirectResponse(url="/profile/personal-info", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/switch-to-user")
async def switch_to_user():
    user_email = db.current_user_email
    user_data = db.get_user_from_db(user_email)
    db.current_user_role = "user"
    
    db.update_user_in_db(user_email, {
        "role": "user", 
        "first_name": user_data['first_name'], 
        "last_name": user_data['last_name']
    })
    db.current_user_data["role"] = "user"
        
    return RedirectResponse(url="/profile/personal-info", status_code=status.HTTP_303_SEE_OTHER)

# --- DİĞER ROTALAR ---

@router.get("/transactions", response_class=HTMLResponse)
async def my_transactions(request: Request):
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "transactions.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "transactions"
    })

@router.get("/properties", response_class=HTMLResponse)
async def agent_properties(request: Request):
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "properties.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "properties"
    })

@router.get("/requests", response_class=HTMLResponse)
async def agent_requests(request: Request):
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "requests.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "requests"
    })

@router.get("/payment", response_class=HTMLResponse)
async def agent_payment_page(request: Request):
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "payment.html", {
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "payment"
    })

# --- ADMIN ROTALARI ---

@router.get("/all-properties", response_class=HTMLResponse)
async def admin_all_properties(request: Request):
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "all_properties.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "all-properties",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png")
    })

@router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request):
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "users.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "users",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png")
    })

@router.get("/approving", response_class=HTMLResponse)
async def admin_approving(request: Request):
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "approving.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "approving",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png")
    })

@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "dashboard.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "dashboard",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png")
    })

@router.get("/system-logs", response_class=HTMLResponse)
async def admin_system_logs(request: Request):
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "system_logs.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "system-logs",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png")
    })

@router.get("/sales-logs", response_class=HTMLResponse)
async def admin_sales_logs(request: Request):
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    return templates.TemplateResponse(request, "sales_logs.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "sales-logs",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png")
    })

# --- HESAPLAMA ---

@router.post("/calculate-booking")
async def calculate_booking(
    request: Request, 
    property_id: str = Form(...), 
    check_in: str = Form(...), 
    check_out: str = Form(...), 
    nights: int = Form(...), 
    guest_info: str = Form(...)
):
    properties_from_db = db.get_properties_from_db()
    property_item = next((p for p in properties_from_db if str(p['id']) == property_id), None)
    
    if not property_item:
        property_item = db.properties.get(property_id)

    if not property_item:
        return {"error": "Mülk bulunamadı"}
        
    base_price = property_item.get("price", 0) or property_item.get("monthly_price", 0)
    daily_price = base_price / 30
    total_price = round(daily_price * nights, 2)
    
    user_data = db.get_user_from_db(db.current_user_email) or db.current_user_data
    
    return templates.TemplateResponse(request, "payment.html", {
        "property": property_item, 
        "check_in": check_in, 
        "check_out": check_out, 
        "nights": nights, 
        "total_price": total_price, 
        "guest_info": guest_info, 
        "role": db.current_user_role,
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "payment"
    })