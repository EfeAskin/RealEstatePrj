import os
from fastapi import FastAPI, Request, Form, status
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI()

# --- DOSYA YOLLARI ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# --- VERİ DEPOSU (9 İLAN EKSİKSİZ) ---
villas = {
    "1": {
        "id": "1", "name": "Villa Shiraz", "location": "Yeşilüzümlü, Fethiye", "monthly_price": 35083, 
        "image": "villa.png", "type": "rent", "guests": 4, "beds": 6, "baths": 2,
        "desc": "Fethiye'nin doğasında, modern mimari ve huzurun buluştuğu lüks kiralık villa."
    },
    "2": {
        "id": "2", "name": "Sea House", "location": "Kaş, Antalya", "monthly_price": 45000, 
        "image": "villa2.png", "type": "rent", "guests": 2, "beds": 2, "baths": 1,
        "desc": "Denize sıfır konumuyla Kaş'ın eşsiz turkuaz sularına açılan kiralık tatil evi."
    },
    "3": {
        "id": "3", "name": "Modern Villa", "location": "Bodrum, Muğla", "monthly_price": 12490000, 
        "image": "villa3.png", "type": "sale", "guests": 8, "beds": 10, "baths": 5,
        "desc": "Bodrum'un en prestijli bölgesinde, ultra lüks detaylarla donatılmış satılık modern malikane."
    },
    "4": {
        "id": "4", "name": "Olive Grove Manor", "location": "Bellapais, Girne, Kuzey Kıbrıs", "monthly_price": 52553, 
        "image": "villa4.png", "type": "rent", "guests": 8, "beds": 4, "baths": 3,
        "desc": "Tarihi Bellapais Manastırı yakınında, zeytin ağaçları içinde huzur dolu, geleneksel taş mimari."
    },
    "5": {
        "id": "5", "name": "Sky Garden Loft", "location": "Girne, Merkez, Kuzey Kıbrıs", "monthly_price": 8500000, 
        "image": "villa5.png", "type": "sale", "guests": 12, "beds": 9, "baths": 4,
        "desc": "Şehrin kalbinde, akıllı ev sistemi ve panoramik şehir manzaralı özel teras bahçesi."
    },
    "6": {
        "id": "6", "name": "Azure Infinity Villa", "location": "Esentepe, Sahil Yolu, Kuzey Kıbrıs", "monthly_price": 45782, 
        "image": "villa6.png", "type": "rent", "guests": 10, "beds": 5, "baths": 5,
        "desc": "Kesintisiz Akdeniz manzarasına açılan sonsuzluk havuzu ve özel plaj erişimi."
    }, 
    "7": {
        "id": "7", "name": "Pine Valley Estate", "location": "Alsancak, Girne, Kuzey Kıbrıs", "monthly_price": 55000, 
        "image": "villa7.png", "type": "rent", "guests": 6, "beds": 4, "baths": 2,
        "desc": "Çam ormanlarının içinde, temiz havası ve dağ manzarasıyla doğa tutkunları için müstakil ev."
    },
    "8": {
        "id": "8", "name": "Golden Sands Penthouse", "location": "İskele, Long Beach, Kuzey Kıbrıs", "monthly_price": 13785600, 
        "image": "villa9.png", "type": "sale", "guests": 10, "beds": 5, "baths": 3,
        "desc": "Ünlü Long Beach sahilinde, rezidans konforu ve 360 derece deniz manzaralı dev teras."
    },
    "9": {
        "id": "9", "name": "Citrus Garden Villa", "location": "Lefke, Kuzey Kıbrıs", "monthly_price": 9850760, 
        "image": "villa8.png", "type": "sale", "guests": 8, "beds": 6, "baths": 3,
        "desc": "Narenciye bahçeleri içerisinde, sakinlik arayanlar için ideal, modern rustik satılık villa."
    }     
}

# Kullanıcı Verileri
users = {
    "efe@cypinvest.com": {"password": "123", "role": "admin", "first_name": "Efe", "last_name": "One"},
    "begench@cypinvest.com": {"password": "456", "role": "admin", "first_name": "Begench", "last_name": "Two"},
    "yahor@cypinvest.com": {"password": "789", "role": "admin", "first_name": "Yahor", "last_name": "Three"},
    "deniz@cypinvest.com": {"password": "312", "role": "admin", "first_name": "Deniz", "last_name": "Four"}
}

# --- AUTH (KAYIT & GİRİŞ) ROTALARI ---

@app.get("/", response_class=HTMLResponse)
async def choose_role(request: Request):
    return templates.TemplateResponse(request, "setrole.html")

@app.get("/login/{role}", response_class=HTMLResponse)
async def login_page(request: Request, role: str):
    return templates.TemplateResponse(request, f"{role}login.html", {"error": "", "role": role})

@app.post("/login/{role}")
async def login(request: Request, role: str, email: str = Form(...), password: str = Form(...)):
    if email in users and users[email]["password"] == password:
        if users[email]["role"] == role:
            return RedirectResponse(url="/home", status_code=status.HTTP_303_SEE_OTHER)
        else:
            error_msg = f"Bu hesap bir {users[email]['role']} hesabıdır!"
    else:
        error_msg = "E-posta veya şifre hatalı!"
    return templates.TemplateResponse(request, f"{role}login.html", {"error": error_msg, "role": role})

@app.get("/register/{role}", response_class=HTMLResponse)
async def register_page(request: Request, role: str):
    if role == "admin": 
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, f"{role}register.html", {"error": "", "role": role})

@app.post("/register/{role}")
async def register(
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
        return templates.TemplateResponse(request, f"{role}register.html", {"error": "Şifreler eşleşmiyor!", "role": role})

    users[email] = {
        "first_name": first_name,
        "last_name": last_name,
        "id": user_id,
        "password": password,
        "role": role
    }
    return RedirectResponse(url=f"/login/{role}", status_code=status.HTTP_303_SEE_OTHER)

# --- ANA SAYFA VE İLANLAR ---

@app.get("/home", response_class=HTMLResponse)
async def home(request: Request):
    # Vitrinde duracak sabit 6 ilan (Ödeme yapan veya öne çıkanlar)
    popular_ids = ["1", "3", "5", "6", "8", "9"]
    popular_villas = [villas[vid] for vid in popular_ids if vid in villas]
    return templates.TemplateResponse(request, "home.html", {"villas": popular_villas})

@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    villa_list = list(villas.values())
    # Search sayfasında 12 kart sınırı
    return templates.TemplateResponse(request, "search.html", {"villas": villa_list[:12]})

@app.get("/villa/{villa_id}", response_class=HTMLResponse)
async def villa_detail(request: Request, villa_id: str):
    villa = villas.get(villa_id)
    if not villa:
        return RedirectResponse(url="/home")
    return templates.TemplateResponse(request, "desktop1.html", {"villa": villa})

# --- HESAPLAMA MOTORU ---

@app.post("/calculate-booking")
async def calculate_booking(
    request: Request,
    villa_id: str = Form(...),
    check_in: str = Form(...),
    check_out: str = Form(...),
    nights: int = Form(...),
    guest_info: str = Form(...)
):
    villa = villas.get(villa_id)
    daily_price = villa["monthly_price"] / 30
    total_price = round(daily_price * nights, 2)
    
    return templates.TemplateResponse(request, "payment.html", {
        "villa": villa,
        "check_in": check_in,
        "check_out": check_out,
        "nights": nights,
        "total_price": total_price,
        "guest_info": guest_info
    })

@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse(request, "about.html")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)