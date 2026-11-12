# BankNavbat — to‘liq Flask loyihasi

Bank xizmatlariga onlayn yozilish tizimi. Loyiha frontend + backend + SQLite ma'lumotlar bazasi + alohida admin paneldan iborat.

## Texnologiyalar
- Backend: Python / Flask
- Database: SQLite (MySQL/PostgreSQL ga DATABASE_URL orqali almashtiriladi)
- Frontend: HTML5, CSS3, JavaScript
- UI/UX: responsive dashboard, cards, forms, status badges

## Ishga tushirish

### 1. Virtual muhit
Windows:
```bash
python -m venv venv
venv\Scripts\activate
```

Linux/macOS:
```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Kutubxonalar
```bash
pip install -r requirements.txt
```

### 3. Ishga tushirish
```bash
python app.py
```

Brauzer:
`http://127.0.0.1:5000`

## Ma'lumotlar bazasi (SQL)
Loyiha SQLAlchemy orqali SQL bazaga ulangan. Standart holatda SQLite ishlatiladi (`instance/banknavbat.db`, jadvallar avtomatik yaratiladi).

MySQL yoki PostgreSQL ga o'tish uchun kod o'zgartirish shart emas, faqat `DATABASE_URL` beriladi:

```bash
pip install PyMySQL            # yoki: pip install psycopg2-binary
export DATABASE_URL="mysql+pymysql://user:parol@localhost:3306/banknavbat?charset=utf8mb4"
python app.py
```
Windows (PowerShell): `$env:DATABASE_URL="..."`. Bazani (`banknavbat`) oldindan yarating; jadvallarni dastur o'zi yaratadi.

## Administrator
Standart (faqat o'quv uchun): `erbolatberdiqulov@bank.uz` / `erbolat73`.
Haqiqiy ishlatishdan oldin `ADMIN_EMAIL`, `ADMIN_PASSWORD` va `SECRET_KEY` ni muhit o'zgaruvchilari orqali o'zgartiring (`.env.example` ga qarang). Admin paroli faqat bazada birinchi marta yaratilganda o'rnatiladi; eski `instance/banknavbat.db` bo'lsa, o'chirib qayta ishga tushiring.

Admin sahifasi: `http://127.0.0.1:5000/admin/login`

## Foydalanuvchi
`/register` orqali ro'yxatdan o'tadi va `/login` orqali kiradi.

## Yangiliklar (v2)
- CSRF himoyasi, POST orqali chiqish, login urinishlarini cheklash, `debug` faqat `FLASK_DEBUG=1` da
- Navbat raqami har kun uchun 101 dan boshlanadi va bazada takrorlanmaydi (unique)
- Bir vaqtga ko'pi bilan 3 kishi; o'tgan vaqt va takroriy yozilish rad etiladi
- Foydalanuvchi navbatini bekor qila oladi; admin holat bo'yicha filtrlaydi, xizmatni qayta faollashtira oladi
- Bosh sahifada haqiqiy keyingi navbat raqami ko'rsatiladi
