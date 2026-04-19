import bcrypt

# --- Şifreleme Fonksiyonları ---
def hash_password(password: str):
    # Şifreyi byte formatına çevirip tuzluyoruz (salt)
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8') # Veritabanında metin olarak saklamak için decode ediyoruz

def verify_password(plain_password, hashed_password):
    password_byte = plain_password.encode('utf-8')
    hashed_byte = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_byte, hashed_byte)

# --- Global Takip Değişkenleri ---
# Uygulama başladığında varsayılan değerler
current_user_email = "user@test.com"
current_user_role = "user"
current_user_data = {
    "first_name": "Mehmet", 
    "last_name": "Müşteri", 
    "phone": "+90 544 333 22 11", 
    "gender": "", 
    "role": "user"
}

# --- VİLLALAR ---
villas = {
    "1": {"id": "1", "name": "Villa Shiraz", "location": "Yeşilüzümlü, Fethiye", "monthly_price": 35083, "image": "villa.png", "type": "rent", "guests": 4, "beds": 6, "baths": 2, "desc": "Fethiye'nin doğasında, modern mimari ve huzurun buluştuğu lüks kiralık villa."},
    "2": {"id": "2", "name": "Sea House", "location": "Kaş, Antalya", "monthly_price": 45000, "image": "villa2.png", "type": "rent", "guests": 2, "beds": 2, "baths": 1, "desc": "Denize sıfır konumuyla Kaş'ın eşsiz turkuaz sularına açılan kiralık tatil evi."},
    "3": {"id": "3", "name": "Modern Villa", "location": "Bodrum, Muğla", "monthly_price": 12490000, "image": "villa3.png", "type": "sale", "guests": 8, "beds": 10, "baths": 5, "desc": "Bodrum'un en prestijli bölgesinde, ultra lüks detaylarla donatılmış satılık modern malikane."},
    "4": {"id": "4", "name": "Olive Grove Manor", "location": "Bellapais, Girne, Kuzey Kıbrıs", "monthly_price": 52553, "image": "villa4.png", "type": "rent", "guests": 8, "beds": 4, "baths": 3, "desc": "Tarihi Bellapais Manastırı yakınında, zeytin ağaçları içinde huzur dolu, geleneksel taş mimari."},
    "5": {"id": "5", "name": "Sky Garden Loft", "location": "Girne, Merkez, Kuzey Kıbrıs", "monthly_price": 8500000, "image": "villa5.png", "type": "sale", "guests": 12, "beds": 9, "baths": 4, "desc": "Şehrin kalbinde, akıllı ev sistemi ve panoramik şehir manzaralı özel teras bahçesi."},
    "6": {"id": "6", "name": "Azure Infinity Villa", "location": "Esentepe, Sahil Yolu, Kuzey Kıbrıs", "monthly_price": 45782, "image": "villa6.png", "type": "rent", "guests": 10, "beds": 5, "baths": 5, "desc": "Kesintisiz Akdeniz manzarasına açılan sonsuzluk havuzu ve özel plaj erişimi."},
    "7": {"id": "7", "name": "Pine Valley Estate", "location": "Alsancak, Girne, Kuzey Kıbrıs", "monthly_price": 55000, "image": "villa7.png", "type": "rent", "guests": 6, "beds": 4, "baths": 2, "desc": "Çam ormanlarının içinde, temiz havası ve dağ manzarasıyla doğa tutkunları için müstakil ev."},
    "8": {"id": "8", "name": "Golden Sands Penthouse", "location": "İskele, Long Beach, Kuzey Kıbrıs", "monthly_price": 13785600, "image": "villa9.png", "type": "sale", "guests": 10, "beds": 5, "baths": 3, "desc": "Ünlü Long Beach sahilinde, rezidans konforu ve 360 derece deniz manzaralı dev teras."},
    "9": {"id": "9", "name": "Citrus Garden Villa", "location": "Lefke, Kuzey Kıbrıs", "monthly_price": 9850760, "image": "villa8.png", "type": "sale", "guests": 8, "beds": 6, "baths": 3, "desc": "Narenciye bahçeleri içerisinde, sakinlik arayanlar için ideal, modern rustik satılık villa."} 
}

# --- KULLANICI VERİLERİ (Genişletilmiş Profil Bilgileri) ---
users = {
    # ADMINLER
    "efe@cypinvest.com": {
        "password": hash_password("123"), 
        "role": "admin", 
        "first_name": "Efe", 
        "last_name": "One",
        "phone": "+90 555 000 00 01",
        "gender": "male",
        "id_no": "10000000001"
    },
    "begench@cypinvest.com": {
        "password": hash_password("456"), 
        "role": "admin", 
        "first_name": "Begench", 
        "last_name": "Two",
        "phone": "+90 555 000 00 02",
        "gender": "male",
        "id_no": "10000000002"
    },
    "yahor@cypinvest.com": {
        "password": hash_password("789"), 
        "role": "admin", 
        "first_name": "Yahor", 
        "last_name": "Three",
        "phone": "+90 555 000 00 03",
        "gender": "male",
        "id_no": "10000000003"
    },
    "deniz@cypinvest.com": {
        "password": hash_password("312"), 
        "role": "admin", 
        "first_name": "Deniz", 
        "last_name": "Four",
        "phone": "+90 555 000 00 04",
        "gender": "male",
        "id_no": "10000000004"
    },

    # AGENT (Emlakçı)
    "agent@test.com": {
        "password": hash_password("123"), 
        "role": "agent", 
        "first_name": "Ahmet", 
        "last_name": "Emlakçı",
        "phone": "+90 532 111 22 33",
        "gender": "male",
        "id_no": "99988877766",
        "iban": "TR12 0006 2000 0000 1234 5678 90",
        "company_name": "CypInvest Gayrimenkul"
    },

    # USER (Müşteri)
    "user@test.com": {
        "password": hash_password("1234"), 
        "role": "user", 
        "first_name": "Mehmet", 
        "last_name": "Müşteri",
        "phone": "+90 544 333 22 11",
        "gender": "", # Opsiyonel
        "email": "user@test.com"
    }
}