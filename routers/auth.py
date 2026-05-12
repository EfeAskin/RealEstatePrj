from fastapi import APIRouter, Request, Form, status
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import database as db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
async def choose_role(request: Request):
    return templates.TemplateResponse(request, "setrole.html")

@router.get("/login/{role}", response_class=HTMLResponse)
async def login_page(request: Request, role: str):
    return templates.TemplateResponse(request, f"{role}login.html", {"error": "", "role": role})

@router.post("/login/{role}")
async def login(request: Request, role: str, email: str = Form(...), password: str = Form(...)):
    # --- CANLI VERİTABANI BAĞLANTISI AKTİF ---
    user = db.get_user_from_db(email)
    # -----------------------------------------

    if user:
        # Şifre doğrulama ve Rol kontrolü
        if db.verify_password(password, user["password"]) and user["role"] == role:
            db.current_user_role = user["role"]
            db.current_user_email = email  
            db.current_user_data = user
            
            if user["role"] == "admin":
                return RedirectResponse(url="/profile/personal-info", status_code=status.HTTP_303_SEE_OTHER)
            else:
                return RedirectResponse(url="/home", status_code=status.HTTP_303_SEE_OTHER)
        else:
            error_msg = f"Hatalı şifre veya bu bir {user['role']} hesabıdır!"
    else:
        error_msg = "E-posta bulunamadı!"
    
    return templates.TemplateResponse(request, f"{role}login.html", {"error": error_msg, "role": role})

@router.get("/logout")
async def logout():
    db.logout_user() # database.py'daki temizleme fonksiyonunu çağırır
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/register/{role}", response_class=HTMLResponse)
async def register_page(request: Request, role: str):
    if role == "admin": 
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, f"{role}register.html", {"error": "", "role": role})

@router.post("/register/{role}")
async def register(
    request: Request, 
    role: str, 
    first_name: str = Form(...), 
    last_name: str = Form(...), 
    email: str = Form(...), 
    password: str = Form(...), 
    confirm_password: str = Form(...),
    phone: str = Form(...),
    user_id: str = Form(None),
    company_name: str = Form(None)
):
    if password != confirm_password:
        return templates.TemplateResponse(request, f"{role}register.html", {
            "error": "Şifreler eşleşmiyor!", 
            "role": role
        })
    
    # --- CANLI VERİTABANI KONTROLÜ ---
    db_user = db.get_user_from_db(email)
    if db_user:
        return templates.TemplateResponse(request, f"{role}register.html", {
            "error": "Bu e-posta adresi zaten kayıtlı!", 
            "role": role
        })

    # Yeni kullanıcıyı veritabanına kaydet
    # database.py içindeki register_user_to_db fonksiyonunu kullanıyoruz
    success = db.register_user_to_db(
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        role=role
    )
    
    if success:
        # Kayıt sonrası ek bilgileri (phone, company vb.) güncellemek için
        # (Eğer veritabanı tablon bu sütunları içeriyorsa)
        db.update_user_in_db(email, {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "gender": ""
        })
        return RedirectResponse(url=f"/login/{role}", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return templates.TemplateResponse(request, f"{role}register.html", {
            "error": "Veritabanı kayıt hatası oluştu!", 
            "role": role
        })