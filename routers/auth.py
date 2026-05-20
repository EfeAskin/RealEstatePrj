from fastapi import APIRouter, Request, Form, status, Response
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
async def login(request: Request, response: Response, role: str, email: str = Form(...), password: str = Form(...)):
    # --- CANLI VERİTABANI BAĞLANTISI AKTİF ---
    user = db.get_user_from_db(email)
    # -----------------------------------------

    if user:
        # Şifre doğrulama ve Rol kontrolü
        if db.verify_password(password, user["password"]) and user["role"] == role:
            # Geriye dönük uyumluluk için eski global durumları da besliyoruz
            db.current_user_role = user["role"]
            db.current_user_email = email  
            db.current_user_data = user
            
            # --- 2. YOL KORUMASI: Tarayıcı bazlı HTTP-Only çerezleri mühürliyotuz ---
            # Böylece Chrome ayrı, Firefox ayrı bir kullanıcı hafızası tutacak
            redirect_url = "/profile/personal-info" if user["role"] == "admin" else "/home"
            res = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
            
            res.set_cookie(
                key="user_id",
                value=str(user["id"]),
                httponly=True,   # JavaScript erişimini engeller, güvenlidir
                max_age=86400,   # 1 gün (saniye cinsinden)
                samesite="lax"
            )
            res.set_cookie(
                key="user_role",
                value=str(user["role"]),
                httponly=False,  # Frontend JS isterse okuyabilsin diye false
                max_age=86400,
                samesite="lax"
            )
            # PROFİL VE MESAJLAŞMA İÇİN KUSURSUZ GÜVENCE: E-posta bilgisini de HTTP-Only çereze mühürlüyoruz
            res.set_cookie(
                key="user_email",
                value=str(user["email"]),
                httponly=True,
                max_age=86400,
                samesite="lax"
            )
            return res
        else:
            error_msg = f"Hatalı şifre veya bu bir {user['role']} hesabıdır!"
    else:
        error_msg = "E-posta bulunamadı!"
    
    return templates.TemplateResponse(request, f"{role}login.html", {"error": error_msg, "role": role})

@router.get("/logout")
async def logout(response: Response):
    db.logout_user() # database.py'daki temizleme fonksiyonunu çağırır
    
    # Çerezleri tarayıcı hafızasından tamamen siliyoruz
    res = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    res.delete_cookie("user_id")
    res.delete_cookie("user_role")
    res.delete_cookie("user_email") # Eklenen yeni çerezi de çıkışta siliyoruz
    return res

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

    # 1. Yeni kullanıcıyı users tablosuna kaydet ve dönen ID'yi al
    new_user_id = db.register_user_to_db(
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        role=role
    )
    
    if new_user_id:
        # 2. Kayıt sonrası ek bilgileri (phone, gender vb.) users tablosunda güncelle
        db.update_user_in_db(email, {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "gender": ""
        })

        # 3. KRİTİK EKLEME: Eğer kullanıcı AGENT ise, agents tablosuna da kaydet
        if role == "agent":
            # PostgreSQL syntax'ına uygun olarak (%) kullanıyoruz ve ID'yi direkt bağlıyoruz
            db.execute_query(
                "INSERT INTO agents (id, agency_name, phone_number, is_verified) VALUES (%s, %s, %s, %s)",
                (new_user_id, company_name if company_name else f"{first_name} Emlak", phone, False)
            )

        return RedirectResponse(url=f"/login/{role}", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return templates.TemplateResponse(request, f"{role}register.html", {
            "error": "Veritabanı kayıt hatası oluştu!", 
            "role": role
        })