import os
from fastapi import FastAPI, Request, Form, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Dosya yolları
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Veri Deposu (Bellek üzerinde)
users = {
    "efe@cypinvest.com": {"password": "123", "role": "admin", "first_name": "Efe", "last_name": "One"},
    "begench@cypinvest.com": {"password": "456", "role": "admin", "first_name": "Begench", "last_name": "Two"},
    "yahor@cypinvest.com": {"password": "789", "role": "admin", "first_name": "Yahor", "last_name": "Three"},
    "deniz@cypinvest.com": {"password": "312", "role": "admin", "first_name": "Deniz", "last_name": "Four"}
}

@app.get("/")
def choose_role(request: Request):
    return templates.TemplateResponse(request=request, name="setrole.html", context={})

@app.get("/login/{role}")
def login_page(request: Request, role: str):
    return templates.TemplateResponse(request=request, name=f"{role}login.html", context={"error": "", "role": role})

@app.post("/login/{role}")
def login(request: Request, role: str, email: str = Form(...), password: str = Form(...)):
    if email in users and users[email]["password"] == password:
        if users[email]["role"] == role:
            return RedirectResponse(url="/home", status_code=status.HTTP_303_SEE_OTHER)
        else:
            error_msg = f"Bu hesap bir {users[email]['role']} hesabıdır!"
    else:
        error_msg = "E-posta veya şifre hatalı!"
    
    return templates.TemplateResponse(request=request, name=f"{role}login.html", context={"error": error_msg, "role": role})

@app.get("/register/{role}")
def register_page(request: Request, role: str):
    if role == "admin": return RedirectResponse(url="/")
    return templates.TemplateResponse(request=request, name=f"{role}register.html", context={"error": "", "role": role})

@app.post("/register/{role}")
def register(
    request: Request,
    role: str,
    first_name: str = Form(...),
    last_name: str = Form(...),
    user_id: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    if password != confirm_password:
        return templates.TemplateResponse(request=request, name=f"{role}register.html", context={"error": "Şifreler eşleşmiyor!", "role": role})

    users[email] = {
        "first_name": first_name,
        "last_name": last_name,
        "id": user_id,
        "password": password,
        "role": role
    }
    return RedirectResponse(url=f"/login/{role}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/home")
def home(request: Request):
    return templates.TemplateResponse(request=request, name="home.html", context={})

@app.get("/search")
def search_page(request: Request):
    return templates.TemplateResponse(request=request, name="search.html", context={})

@app.get("/about")
def about_page(request: Request):
    return templates.TemplateResponse(request=request, name="about.html", context={})