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
    if email in db.users:
        user = db.users[email]
        # Şifre doğruluğu ve Rol kontrolü
        if db.verify_password(password, user["password"]) and user["role"] == role:
            # Oturum bilgilerini global değişkenlere aktar
            db.current_user_role = user["role"]
            db.current_user_email = email  # Profil sayfasında mailin gözükmesini sağlayan kritik satır
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
    db.current_user_role = None
    db.current_user_email = None
    db.current_user_data = {"first_name": "", "last_name": ""}
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
    phone: str = Form(...),             # HTML'deki name="phone"
    user_id: str = Form(None),          # Agent HTML'indeki name="user_id"
    company_name: str = Form(None)      # Agent HTML'indeki name="company_name"
):
    # 1. Şifrelerin eşleşme kontrolü
    if password != confirm_password:
        return templates.TemplateResponse(request, f"{role}register.html", {
            "error": "Şifreler eşleşmiyor!", 
            "role": role
        })
    
    # 2. E-posta sistemde zaten var mı?
    if email in db.users:
        return templates.TemplateResponse(request, f"{role}register.html", {
            "error": "Bu e-posta adresi zaten kayıtlı!", 
            "role": role
        })

    # 3. Yeni kullanıcı verisi oluşturma (Hiçbir alan eksik değil)
    user_entry = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "password": db.hash_password(password),
        "role": role,
        "phone": phone,
        "gender": ""  # İlk kayıt aşamasında boş, profil sayfasında güncellenebilir
    }

    # Eğer Agent ise Agent'a özel HTML alanlarını ekle
    if role == "agent":
        user_entry["id_no"] = user_id        # HTML'deki name="user_id" (Licence No)
        user_entry["company_name"] = company_name
        user_entry["iban"] = ""              # Daha sonra Modal üzerinden doldurulacak

    # 4. Veriyi 'veritabanına' (sözlüğe) yaz
    db.users[email] = user_entry
    
    # Kayıt başarılı, login sayfasına gönder
    return RedirectResponse(url=f"/login/{role}", status_code=status.HTTP_303_SEE_OTHER)