#!/usr/bin/env python3
"""FastAPI backend for the I-See project.

Run with: uvicorn backend.server:app --host 127.0.0.1 --port 4173 --reload
Swagger UI: /docs
"""
import json, os, re, secrets, threading, time, sqlite3, shutil, subprocess
import hashlib, ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import certifi
try:
    import free_search  # started as `python backend/server.py`
    import diet_match
except ImportError:
    from backend import free_search  # imported as the `backend.server` module
    from backend import diet_match

from fastapi import FastAPI, HTTPException, Header, Query, Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent.parent
PAGES = BASE / "frontend" / "pages"
ASSETS = BASE / "frontend" / "assets"

def load_dotenv(path: Path):
    """Load simple KEY=value settings without requiring an extra package."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

load_dotenv(BASE / ".env")
STORE_RADIUS_METERS = 2000
# Mirrors are queried in parallel: some of them silently hang on certain networks.
STORE_PROVIDERS = ("https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter")
DB_PATH = Path(os.getenv("DATABASE_PATH", BASE / "data" / "isee.sqlite3"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
# Uploaded story photos live next to the database so they survive redeploys (the Docker volume).
UPLOADS = DB_PATH.parent / "uploads"
UPLOADS.mkdir(exist_ok=True)
UPLOAD_MAX_BYTES = 5 * 1024 * 1024
UPLOAD_TYPES = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"RIFF", "webp"))
TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())

SESSION_TTL_SECONDS = 30 * 24 * 3600
PASSWORD_ITERATIONS = 200_000
lock = threading.RLock()
AI_CACHE_SECONDS = int(os.getenv("AI_CACHE_DAYS", "30")) * 24 * 3600
ai_request_times = {}
# Paid providers that answered «no quota / no credits / wrong country» are skipped for an hour.
provider_cooldown = {}
PROVIDER_COOLDOWN_SECONDS = 3600
ai_lock = threading.Lock()
AI_ENRICHMENT_FIELDS = ("product_name", "ingredients", "allergens", "additives", "product_info", "nutrition")
AI_FIELD_LIMITS = {"product_name": 180, "ingredients": 4000, "allergens": 1000, "additives": 1000, "product_info": 1800, "nutrition": 1800}

def db():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"

def verify_password(password, stored):
    """Check a PBKDF2 hash; plain-text values from old demo databases are still accepted."""
    if not stored.startswith("pbkdf2_sha256$"):
        return secrets.compare_digest(password.encode(), stored.encode())
    _, iterations, salt, digest = stored.split("$", 3)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    return secrets.compare_digest(candidate, digest)

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def seed_admin_password():
    """Demo password locally; on a public server ADMIN_PASSWORD or a random one printed once to the log."""
    password = os.getenv("ADMIN_PASSWORD", "").strip()
    if password:
        return password
    if os.getenv("HOST", "127.0.0.1") in ("127.0.0.1", "localhost", "::1"):
        return "12345"
    password = secrets.token_urlsafe(12)
    print(f"Создан администратор: логин admin, пароль {password} (задайте ADMIN_PASSWORD, чтобы выбрать свой)", flush=True)
    return password

# Каталог «Товары для вас»: живёт в базе, страница получает его через GET /api/products.
CATALOG_SEED = [
    ("Йогурт клубничный", "Молочные продукты", "4601234567890", "молоко, клубника, сахар, закваска", "молоко", 89),
    ("Кефир 1%", "Молочные продукты", "4601234570001", "нормализованное молоко, закваска кефирных грибков", "молоко", 74),
    ("Творог зернистый", "Молочные продукты", "4601234570002", "молоко, сливки, соль, закваска", "молоко", 119),
    ("Сыр Российский", "Молочные продукты", "4601234570003", "молоко, соль, сычужный фермент, закваска", "молоко", 289),
    ("Сметана 15%", "Молочные продукты", "4601234570004", "сливки, закваска", "молоко", 69),
    ("Молоко 2,5%", "Молочные продукты", "4601234570005", "цельное молоко", "молоко", 92),
    ("Хлеб пшеничный", "Выпечка", "4601234567891", "пшеничная мука, вода, дрожжи, соль", "пшеница, глютен", 65),
    ("Батон нарезной", "Выпечка", "4601234570007", "пшеничная мука, вода, сахар, подсолнечное масло, дрожжи", "пшеница, глютен", 58),
    ("Булочка с маком", "Выпечка", "4601234570008", "пшеничная мука, мак, сахар, молоко, яйца, дрожжи", "пшеница, глютен, молоко, яйца", 45),
    ("Круассан с шоколадом", "Выпечка", "4601234570009", "пшеничная мука, сливочное масло, шоколад, сахар, дрожжи", "пшеница, глютен, молоко", 79),
    ("Хлеб ржаной", "Выпечка", "4601234570010", "ржаная мука, пшеничная мука, вода, солод, соль", "рожь, пшеница, глютен", 62),
    ("Шоколад с орехами", "Сладости", "4601234567892", "какао, сахар, фундук, молоко", "фундук, орехи, молоко", 149),
    ("Печенье овсяное", "Сладости", "4601234570012", "овсяные хлопья, пшеничная мука, сахар, сливочное масло, яйца", "глютен, пшеница, яйца, молоко", 98),
    ("Зефир ванильный", "Сладости", "4601234570013", "яблочное пюре, сахар, яичный белок, агар, ваниль", "яйца", 135),
    ("Мармелад фруктовый", "Сладости", "4601234570014", "сахар, фруктовое пюре, пектин, лимонная кислота", "", 88),
    ("Вафли со сгущёнкой", "Сладости", "4601234570015", "пшеничная мука, сгущённое молоко, сахар, масло", "пшеница, глютен, молоко", 76),
    ("Гречка ядрица", "Крупы и макароны", "4601234570016", "гречневая крупа", "", 112),
    ("Рис круглозёрный", "Крупы и макароны", "4601234570017", "рис", "", 96),
    ("Овсяные хлопья", "Крупы и макароны", "4601234570018", "овсяные хлопья", "овёс, глютен", 84),
    ("Спагетти", "Крупы и макароны", "4601234570019", "мука из твёрдой пшеницы, вода", "пшеница, глютен", 79),
    ("Сок яблочный", "Напитки", "4601234570020", "яблочный сок", "", 119),
    ("Сок апельсиновый", "Напитки", "4601234570021", "апельсиновый сок", "", 129),
    ("Чай зелёный", "Напитки", "4601234570022", "зелёный чай, лепестки жасмина", "", 139),
    ("Лимонад лимон-мята", "Напитки", "4601234570023", "вода, сахар, лимонный сок, мята, лимонная кислота", "", 85),
    ("Арахис жареный", "Орехи и снеки", "4601234570024", "арахис, соль", "арахис", 109),
    ("Чипсы картофельные", "Орехи и снеки", "4601234570025", "картофель, подсолнечное масло, соль", "", 119),
    ("Миндаль сушёный", "Орехи и снеки", "4601234570026", "миндаль", "миндаль, орехи", 249),
    ("Колбаса варёная", "Мясо и рыба", "4601234570027", "говядина, свинина, молоко, соль, специи", "молоко", 219),
    ("Филе куриное", "Мясо и рыба", "4601234570028", "куриное филе", "", 299),
    ("Горбуша консервированная", "Мясо и рыба", "4601234570029", "горбуша, масло, соль", "рыба", 135),
]

# Starter content of the two system stories.
STORY_KINDS = ("article", "recipe", "guide")
STORY_HOW_BODY = "Откройте главную страницу и нажмите «Сканировать».\nРазрешите сайту пользоваться камерой телефона.\nНаведите камеру на штрихкод на упаковке и подержите пару секунд.\nПрочитайте состав: он появится крупными буквами, а сложные слова мы объясним.\nЕсли в составе есть то, что вам нельзя, вы увидите предупреждение."
STORY_TEAM_BODY = "«Я Вижу!» придумали, чтобы покупки снова были спокойными. Мелкий шрифт на упаковке трудно разглядеть, а названия вроде «Е330» или «мальтодекстрин» ничего не говорят.\n\nМы читаем упаковку за вас: показываем состав крупно и объясняем непонятные слова простым языком. А если в продукте есть то, что вам нельзя, сразу предупреждаем.\n\nЕсли что-то неудобно или непонятно, напишите нам через «Обратную связь» — мы читаем каждое сообщение."

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (login TEXT PRIMARY KEY, password TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', is_admin INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL, barcode TEXT NOT NULL DEFAULT '', ingredients TEXT NOT NULL DEFAULT '', allergens TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS profiles (login TEXT PRIMARY KEY REFERENCES users(login) ON DELETE CASCADE, restrictions TEXT NOT NULL DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS checks (id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT NOT NULL REFERENCES users(login), product_id INTEGER REFERENCES products(id) ON DELETE SET NULL, product_name TEXT NOT NULL, barcode TEXT NOT NULL DEFAULT '', checked_at TEXT NOT NULL, result TEXT NOT NULL, reason TEXT, matches TEXT NOT NULL DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS check_matches (check_id INTEGER NOT NULL REFERENCES checks(id) ON DELETE CASCADE, restriction TEXT NOT NULL, PRIMARY KEY(check_id, restriction));
    CREATE TABLE IF NOT EXISTS stories (id TEXT PRIMARY KEY, title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '', image TEXT NOT NULL, href TEXT NOT NULL DEFAULT 'help.html');
    CREATE TABLE IF NOT EXISTS recipes (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', image TEXT NOT NULL, ingredients TEXT NOT NULL DEFAULT '[]', steps TEXT NOT NULL DEFAULT '[]', sponsored_product TEXT NOT NULL DEFAULT '', sponsored_label TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS ai_cache (cache_key TEXT PRIMARY KEY, response TEXT NOT NULL, expires_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, login TEXT NOT NULL REFERENCES users(login) ON DELETE CASCADE, expires_at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_sessions_login ON sessions(login);
    CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
    CREATE INDEX IF NOT EXISTS idx_checks_login_date ON checks(login, checked_at);
    CREATE INDEX IF NOT EXISTS idx_check_matches_restriction ON check_matches(restriction);
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "phone" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone) WHERE phone <> ''")
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
    story_columns = {row[1] for row in conn.execute("PRAGMA table_info(stories)")}
    if "recipe_id" not in story_columns:
        conn.execute("ALTER TABLE stories ADD COLUMN recipe_id TEXT REFERENCES recipes(id) ON DELETE SET NULL")
    # What opens inside a story: an article, a recipe or a step-by-step guide.
    if "kind" not in story_columns:
        conn.execute("ALTER TABLE stories ADD COLUMN kind TEXT NOT NULL DEFAULT 'article'")
        conn.execute("ALTER TABLE stories ADD COLUMN body TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE stories SET kind='recipe' WHERE recipe_id IS NOT NULL AND recipe_id <> ''")
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        # A fresh database starts with the administrator only; people sign up themselves.
        conn.execute("INSERT INTO users(login,password,name,phone,is_admin) VALUES (?,?,?,?,?)", ("admin", hash_password(seed_admin_password()), "Администратор", "", 1))
        conn.execute("INSERT INTO profiles VALUES (?,?)", ("admin", "[]"))
    # Once per database (user_version 0 → 1) the catalog is filled up by name: products the
    # admin edited stay as they are, and ones the admin deletes later do not come back.
    if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
        known = {row[0] for row in conn.execute("SELECT name FROM products")}
        conn.executemany("INSERT INTO products(name,category,barcode,ingredients,allergens,price) VALUES (?,?,?,?,?,?)", [row for row in CATALOG_SEED if row[0] not in known])
        conn.execute("PRAGMA user_version = 1")
    if conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 0:
        rows = [("story-how", "Как пользоваться сервисом", "Сканируйте продукты и проверяйте состав", "story-how.jpg", "/help.html", None), ("story-team", "Команда проекта «Я Вижу!»", "Создано с заботой о ваших покупках", "story-team.jpg", "/help.html", None)]
        conn.executemany("INSERT INTO stories(id,title,subtitle,image,href,recipe_id) VALUES (?,?,?,?,?,?)", rows)
    else:
        existing_stories = conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
        if existing_stories == 7 and conn.execute("SELECT 1 FROM stories WHERE id='story-how'").fetchone() is None:
            conn.execute("DELETE FROM stories")
            conn.executemany("INSERT INTO stories(id,title,subtitle,image,href,recipe_id) VALUES (?,?,?,?,?,?)", [("story-how", "Как пользоваться сервисом", "Сканируйте продукты и проверяйте состав", "story-how.jpg", "/help.html", None), ("story-team", "Команда проекта «Я Вижу!»", "Создано с заботой о ваших покупках", "story-team.jpg", "/help.html", None)])
    # An empty image means "use the linked recipe's photo"; older recipe stories kept a stock photo instead.
    conn.execute("UPDATE stories SET image='' WHERE recipe_id IS NOT NULL AND recipe_id <> '' AND image LIKE 'story-__.jpg'")
    conn.execute("UPDATE stories SET kind='guide', body=? WHERE id='story-how' AND body=''", (STORY_HOW_BODY,))
    conn.execute("UPDATE stories SET kind='article', body=? WHERE id='story-team' AND body=''", (STORY_TEAM_BODY,))
    # System stories have their own illustrations; older databases still point at the shared photos.
    conn.execute("UPDATE stories SET image='story-how.jpg' WHERE id='story-how' AND image='story-01.jpg'")
    conn.execute("UPDATE stories SET image='story-team.jpg' WHERE id='story-team' AND image='story-02.jpg'")
    if conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0] < 50:
        recipes = [
            ("recipe-01", "Тёплая овсянка с яблоком", "Быстрый завтрак с корицей и хрустящими яблоками.", "recipe-01.jpg", json.dumps(["овсяные хлопья — 60 г", "молоко — 200 мл", "яблоко — 1 шт.", "корица — по вкусу"], ensure_ascii=False), json.dumps(["Смешайте хлопья и молоко в сотейнике.", "Варите 5 минут на слабом огне.", "Добавьте яблоко и корицу перед подачей."], ensure_ascii=False), "Овсяные хлопья «Я Вижу!»", "РЕКЛАМНАЯ ИНТЕГРАЦИЯ"),
            ("recipe-02", "Паста с овощами", "Простой ужин из сезонных овощей.", "recipe-02.jpg", json.dumps(["паста — 200 г", "томаты — 2 шт.", "кабачок — 1 шт.", "оливковое масло — 1 ст. л."], ensure_ascii=False), json.dumps(["Отварите пасту до состояния al dente.", "Обжарьте овощи 7–8 минут.", "Смешайте пасту с овощами и подайте горячей."], ensure_ascii=False), "Томаты «Солнечный сад»", "РЕКЛАМНЫЙ ПРОДУКТ"),
            ("recipe-03", "Йогуртовый десерт", "Лёгкий десерт без выпечки.", "recipe-03.jpg", json.dumps(["йогурт — 250 г", "ягоды — 100 г", "гранола — 50 г"], ensure_ascii=False), json.dumps(["Выложите йогурт в стакан.", "Добавьте ягоды и гранолу слоями.", "Охладите 20 минут."], ensure_ascii=False), "Йогурт «Лесная ягода»", "РЕКЛАМНАЯ ИНТЕГРАЦИЯ"),
        ]
        conn.executemany("INSERT OR IGNORE INTO recipes VALUES (?,?,?,?,?,?,?,?)", recipes)
        conn.execute("UPDATE stories SET recipe_id='recipe-01',href='/recipe.html?id=recipe-01' WHERE id='story-01'")
        conn.execute("UPDATE stories SET recipe_id='recipe-02',href='/recipe.html?id=recipe-02' WHERE id='story-02'")
        conn.execute("UPDATE stories SET recipe_id='recipe-03',href='/recipe.html?id=recipe-03' WHERE id='story-03'")
        bases = [("Салат", ["овощи", "оливковое масло"]), ("Суп", ["овощи", "бульон"]), ("Запеканка", ["картофель", "сыр"]), ("Боул", ["рис", "авокадо"]), ("Сэндвич", ["хлеб", "томат"]), ("Печенье", ["мука", "сахар"]), ("Смузи", ["банан", "ягоды"]), ("Рис с овощами", ["рис", "морковь"]), ("Каша", ["крупа", "молоко"]), ("Рагу", ["кабачок", "морковь"])]
        extra = []
        for i in range(4, 51):
            base, ingredients = bases[(i - 4) % len(bases)]
            suffix = ["с орехами", "с молоком", "с яйцом", "с рыбой", "с курицей"][((i - 4) // len(bases)) % 5]
            extra_ingredients = ingredients + ([suffix[2:]] if suffix[2:] in ("орехами", "молоком", "яйцом", "рыбой", "курицей") else [])
            extra.append((f"recipe-{i:02d}", f"{base} {suffix} №{i}", f"Домашний рецепт {base.lower()} с понятными ингредиентами.", f"recipe-{i:02d}.jpg", json.dumps(extra_ingredients, ensure_ascii=False), json.dumps(["Подготовьте ингредиенты.", "Смешайте или приготовьте до готовности.", "Подавайте сразу."], ensure_ascii=False), "", ""))
        conn.executemany("INSERT OR IGNORE INTO recipes VALUES (?,?,?,?,?,?,?,?)", extra)
    conn.commit(); conn.close()

def rowdict(row): return dict(row) if row else None
def rows(table):
    conn=db(); result=[dict(x) for x in conn.execute(f"SELECT * FROM {table}")]; conn.close(); return result

init_db()

SWAGGER_TAGS = [
    {"name": "Система", "description": "Проверка доступности и состояния сервера."},
    {"name": "Авторизация", "description": "Вход пользователей и выдача bearer-токенов."},
    {"name": "Каталог товаров", "description": "Получение и управление товарами каталога."},
    {"name": "Профиль и проверки", "description": "Ограничения питания и личная история проверок."},
    {"name": "Истории", "description": "Истории, отображаемые на главной странице."},
    {"name": "Администрирование", "description": "Защищённые операции администратора."},
    {"name": "Магазины", "description": "Поиск ближайших магазинов через OpenStreetMap."},
    {"name": "Open Food Facts", "description": "Получение данных о продукте по штрихкоду."},
    {"name": "Поиск состава с ИИ", "description": "Поиск недостающих сведений о конкретном продукте с веб-источниками. Результат требует проверки по упаковке."},
]
app = FastAPI(title="Я Вижу! API", description="API сервиса проверки состава продуктов", version="1.0.0", openapi_tags=SWAGGER_TAGS)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class LoginData(BaseModel): login: str; password: str
class RegistrationData(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=10, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    restrictions: list[dict] = Field(default_factory=list, max_length=100)
class ProductData(BaseModel):
    name: str = Field(min_length=1, max_length=120); category: str = "Продукты"; barcode: str = ""; ingredients: str = ""; allergens: str = ""; price: int = Field(default=0, ge=0, le=10000000)
class DietItem(BaseModel): id: str = Field(min_length=1, max_length=80); text: str = Field(max_length=2000)
class DietCheckData(BaseModel): items: list[DietItem] = Field(default_factory=list, max_length=200)
class ProfileData(BaseModel): restrictions: list[dict] = Field(default_factory=list, max_length=100)
class CheckData(BaseModel): product_id: int | None = None; product: dict | None = None
class StoryData(BaseModel): id: str = ""; title: str = Field(min_length=1, max_length=60); subtitle: str = ""; image: str = ""; href: str = "help.html"; recipe_id: str | None = None; kind: str = "article"; body: str = Field(default="", max_length=6000)
class RecipeData(BaseModel): id: str = ""; title: str = Field(min_length=1, max_length=120); description: str = ""; image: str = "story-01.jpg"; ingredients: list[str] = Field(default_factory=list, max_length=30); steps: list[str] = Field(default_factory=list, max_length=20); sponsored_product: str = ""; sponsored_label: str = ""
class ProductLookupData(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    brand: str = Field(default="", max_length=120)
    barcode: str = Field(default="", max_length=32)
    country: str = Field(default="Россия", max_length=80)
    missing: list[str] = Field(default_factory=lambda: ["ingredients", "allergens", "product_info", "nutrition", "additives"], max_length=5)
    known_data: dict = Field(default_factory=dict)

def normalize_phone(value):
    raw = str(value or '').strip()
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    if len(digits) not in range(10, 16):
        raise HTTPException(422, 'Укажите корректный номер телефона')
    return f'+{digits}'

def phone_is_registered(phone):
    conn = db()
    try:
        return bool(conn.execute("SELECT 1 FROM users WHERE phone=? AND phone<>''", (phone,)).fetchone())
    finally:
        conn.close()

def clean_restrictions(items):
    clean = []
    seen = set()
    for item in items or []:
        if isinstance(item, dict) and item.get('type') in ('allergy', 'avoid'):
            name = str(item.get('name', item.get('food', ''))).strip()[:80]
            key = (item['type'], name.casefold())
            if name and key not in seen:
                seen.add(key)
                clean.append({'type': item['type'], 'name': name})
    return clean

def public_user(account):
    return {
        'login': account['login'],
        'name': account['name'],
        'phone': account['phone'] or '',
        'is_admin': bool(account['is_admin']),
    }

def bearer_token(authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "): return None
    return authorization.split(" ", 1)[1].strip() or None
def issue_token(login):
    token = secrets.token_urlsafe(32)
    conn = db()
    try:
        conn.execute("INSERT INTO sessions(token_hash,login,expires_at) VALUES (?,?,?)", (token_hash(token), login, int(time.time()) + SESSION_TTL_SECONDS))
        conn.commit()
    finally:
        conn.close()
    return token
def user_from_token(authorization: str | None):
    token = bearer_token(authorization)
    if not token: return None
    conn = db()
    try:
        row = conn.execute("SELECT login FROM sessions WHERE token_hash=? AND expires_at>?", (token_hash(token), int(time.time()))).fetchone()
    finally:
        conn.close()
    return row[0] if row else None
def require_user(authorization):
    user = user_from_token(authorization)
    if not user: raise HTTPException(401, "Войдите в профиль для этого действия")
    return user
def require_admin(authorization):
    user = require_user(authorization)
    conn=db(); admin=conn.execute("SELECT is_admin FROM users WHERE login=?",(user,)).fetchone(); conn.close()
    if not admin or not admin[0]: raise HTTPException(403, "Это действие доступно только администратору")
    return user
def clean_product(data):
    return {"name": data.name.strip(), "category": data.category.strip()[:80], "barcode": data.barcode.strip()[:32], "ingredients": data.ingredients.strip()[:2000], "allergens": data.allergens.strip()[:500], "price": data.price}

@app.get("/api/health", tags=["Система"], summary="Проверить работу сервера", description="Возвращает простой признак доступности backend-сервера. Авторизация не требуется.")
def health(): return {"ok": True}
@app.get("/api/register/check", tags=["Авторизация"], summary="Проверить телефон", description="Проверяет формат и доступность номера телефона до создания профиля.")
def check_registration_phone(phone: str = Query(..., min_length=10, max_length=32)):
    normalized = normalize_phone(phone)
    registered = phone_is_registered(normalized)
    return {"available": not registered, "phone": normalized}
@app.post("/api/register", status_code=201, tags=["Авторизация"], summary="Создать профиль", description="Создаёт профиль по имени и телефону, сохраняет ограничения и сразу выдаёт bearer-токен.")
def register(data: RegistrationData):
    name = data.name.strip()
    if not name or re.search(r'[\d<>]', name):
        raise HTTPException(422, "Укажите корректное имя")
    phone = normalize_phone(data.phone)
    restrictions = clean_restrictions(data.restrictions)
    login = f"phone:{phone.lstrip('+')}"
    password = hash_password(data.password)
    conn = db()
    try:
        if phone_is_registered(phone):
            raise HTTPException(409, "Этот номер уже зарегистрирован")
        while conn.execute("SELECT 1 FROM users WHERE login=?", (login,)).fetchone():
            login = f"phone:{secrets.token_hex(8)}"
        conn.execute("BEGIN")
        conn.execute("INSERT INTO users(login,password,name,phone,is_admin) VALUES (?,?,?,?,0)", (login, password, name, phone))
        conn.execute("INSERT INTO profiles(login,restrictions) VALUES (?,?)", (login, json.dumps(restrictions, ensure_ascii=False)))
        conn.commit()
        account = rowdict(conn.execute("SELECT * FROM users WHERE login=?", (login,)).fetchone())
    except HTTPException:
        conn.rollback()
        conn.close()
        raise
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        raise HTTPException(409, "Не удалось создать профиль с этим номером")
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return {"token": issue_token(login), "user": public_user(account)}

def find_account(identifier):
    """Find a user by demo login or by phone number given at registration."""
    conn = db()
    try:
        account = rowdict(conn.execute("SELECT * FROM users WHERE login=?", (identifier,)).fetchone())
        if not account and re.fullmatch(r"\+?[\d\s().-]{10,32}", identifier):
            try:
                phone = normalize_phone(identifier)
            except HTTPException:
                return None
            account = rowdict(conn.execute("SELECT * FROM users WHERE phone=? AND phone<>''", (phone,)).fetchone())
        return account
    finally:
        conn.close()

@app.post("/api/login", tags=["Авторизация"], summary="Войти в аккаунт", description="Проверяет логин или телефон и пароль, после чего выдаёт bearer-токен на 30 дней.")
def login(data: LoginData):
    account = find_account(data.login.strip())
    if not account or not verify_password(data.password, account["password"]): raise HTTPException(401, "Неверный логин, телефон или пароль")
    if not account["password"].startswith("pbkdf2_sha256$"):
        conn=db(); conn.execute("UPDATE users SET password=? WHERE login=?", (hash_password(data.password), account["login"])); conn.commit(); conn.close()
    return {"token": issue_token(account["login"]), "user": public_user(account)}

@app.post("/api/logout", tags=["Авторизация"], summary="Выйти из аккаунта", description="Отзывает текущий bearer-токен.")
def logout(authorization: str | None = Header(default=None)):
    token = bearer_token(authorization)
    if token:
        conn=db(); conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),)); conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/products", tags=["Каталог товаров"], summary="Получить каталог товаров", description="Возвращает все товары, доступные на странице каталога. Авторизация не требуется.")
def get_products(): return rows("products")
@app.post("/api/products", status_code=201, tags=["Каталог товаров"], summary="Добавить товар в каталог", description="Создаёт новый товар в каталоге. Доступно только администратору с bearer-токеном.")
def add_product(data: ProductData, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    item=clean_product(data); conn=db(); cur=conn.execute("INSERT INTO products(name,category,barcode,ingredients,allergens,price) VALUES (:name,:category,:barcode,:ingredients,:allergens,:price)",item); conn.commit(); item={"id":cur.lastrowid,**item}; conn.close(); return item
@app.get("/api/products/{item_id}", tags=["Каталог товаров"], summary="Получить один товар", description="Возвращает подробную информацию о товаре по его числовому идентификатору.")
def get_product(item_id: int):
    conn=db(); item=rowdict(conn.execute("SELECT * FROM products WHERE id=?",(item_id,)).fetchone()); conn.close()
    if not item: raise HTTPException(404, "Товар не найден")
    return item
@app.put("/api/products/{item_id}", tags=["Каталог товаров"], summary="Изменить товар", description="Полностью обновляет данные товара. Доступно только администратору с bearer-токеном.")
def update_product(item_id: int, data: ProductData, authorization: str | None = Header(default=None)):
    require_admin(authorization); item = clean_product(data); conn=db()
    exists=conn.execute("SELECT 1 FROM products WHERE id=?",(item_id,)).fetchone()
    if not item: raise HTTPException(404, "Товар не найден")
    if not exists: conn.close(); raise HTTPException(404, "Товар не найден")
    conn.execute("UPDATE products SET name=:name,category=:category,barcode=:barcode,ingredients=:ingredients,allergens=:allergens,price=:price WHERE id=:id", {**item,"id":item_id}); conn.commit(); conn.close(); return {"id":item_id,**item}
@app.delete("/api/products/{item_id}", tags=["Каталог товаров"], summary="Удалить товар", description="Удаляет товар из каталога по идентификатору. Доступно только администратору с bearer-токеном.")
def delete_product(item_id: int, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    conn=db(); item=rowdict(conn.execute("SELECT * FROM products WHERE id=?",(item_id,)).fetchone())
    if item: conn.execute("DELETE FROM products WHERE id=?",(item_id,)); conn.commit(); conn.close(); return {"deleted":item}
    conn.close()
    raise HTTPException(404, "Товар не найден")

@app.get("/api/profile", tags=["Профиль и проверки"], summary="Получить ограничения профиля", description="Возвращает сохранённые аллергии и продукты, которых пользователь избегает. Требуется авторизация.")
def get_profile(authorization: str | None = Header(default=None)):
    user = require_user(authorization); conn=db(); row=conn.execute("SELECT restrictions FROM profiles WHERE login=?",(user,)).fetchone(); conn.close(); return {"restrictions": json.loads(row[0]) if row else []}
@app.post("/api/profile", tags=["Профиль и проверки"], summary="Сохранить ограничения профиля", description="Сохраняет список аллергий и ограничений питания текущего пользователя. Требуется авторизация.")
def save_profile(data: ProfileData, authorization: str | None = Header(default=None)):
    user = require_user(authorization); clean = clean_restrictions(data.restrictions)
    conn=db(); conn.execute("INSERT INTO profiles(login,restrictions) VALUES (?,?) ON CONFLICT(login) DO UPDATE SET restrictions=excluded.restrictions",(user,json.dumps(clean,ensure_ascii=False))); conn.commit(); conn.close(); return {"restrictions": clean}
@app.post("/api/diet/check", tags=["Профиль и проверки"], summary="Что из списка мне нельзя", description="Сравнивает товары или рецепты с ограничениями профиля: сразу по словам (молоко — это и кефир, и сливочное масло), а нейросеть в фоне ищет неочевидные совпадения. Пока она думает, ai = pending: повторите запрос через несколько секунд. Требуется авторизация.")
def diet_check(data: DietCheckData, authorization: str | None = Header(default=None)):
    user = require_user(authorization); conn=db(); row=conn.execute("SELECT restrictions FROM profiles WHERE login=?",(user,)).fetchone(); conn.close()
    names = [x["name"] for x in (json.loads(row[0]) if row else [])]
    results, ai = diet_match.check(names, [(item.id, item.text) for item in data.items], read_ai_cache, write_ai_cache)
    return {"restrictions": names, "results": results, "ai": ai}
@app.get("/api/checks", tags=["Профиль и проверки"], summary="Получить историю проверок", description="Возвращает только проверки текущего авторизованного пользователя, отсортированные в порядке сохранения.")
def get_checks(authorization: str | None = Header(default=None)):
    user = require_user(authorization); conn=db(); result=[]
    # JOIN: the name and category come from the current products row; the copy saved with the
    # check is only a fallback for a product that has since been deleted (product_id is NULL).
    for x in conn.execute("""SELECT c.id, c.login, c.product_id, COALESCE(p.name, c.product_name) AS product_name, p.category AS product_category,
            c.barcode, c.checked_at, c.result, c.reason, c.matches
        FROM checks c LEFT JOIN products p ON p.id = c.product_id WHERE c.login = ? ORDER BY c.id""", (user,)):
        item=dict(x); item["user"]=item.pop("login"); item["matches"]=json.loads(item["matches"]); result.append(item)
    conn.close(); return result
@app.post("/api/checks", status_code=201, tags=["Профиль и проверки"], summary="Проверить и сохранить товар", description="Сравнивает состав товара с ограничениями профиля, рассчитывает результат проверки и сохраняет запись в личную историю пользователя.")
def save_check(data: CheckData, authorization: str | None = Header(default=None)):
    user = require_user(authorization); conn=db(); product=rowdict(conn.execute("SELECT * FROM products WHERE id=?",(data.product_id,)).fetchone())
    if not product and data.product:
        product = {"id": None, "name": str(data.product.get("name", "")).strip(), "barcode": str(data.product.get("barcode", "")), "ingredients": str(data.product.get("ingredients", "")), "allergens": str(data.product.get("allergens", ""))}
    if not product or not product.get("name"): raise HTTPException(404, "Товар не найден")
    prow=conn.execute("SELECT restrictions FROM profiles WHERE login=?",(user,)).fetchone(); restrictions=[x["name"].casefold() for x in (json.loads(prow[0]) if prow else [])]; source = f"{product.get('allergens', '')} {product.get('ingredients', '')}".casefold(); matches = [x for x in restrictions if x in source]
    result = "warning" if matches else "clear" if restrictions and source.strip() else "unknown"; reason = None if result != "unknown" else "no_restrictions" if not restrictions else "product_data_missing"
    record = {"user": user, "product_id": product.get("id"), "product_name": product["name"], "barcode": product.get("barcode", ""), "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "result": result, "reason": reason, "matches": matches}
    try:
        conn.execute("BEGIN"); cur=conn.execute("INSERT INTO checks(login,product_id,product_name,barcode,checked_at,result,reason,matches) VALUES (?,?,?,?,?,?,?,?)",(user,record["product_id"],record["product_name"],record["barcode"],record["checked_at"],result,reason,json.dumps(matches,ensure_ascii=False))); record["id"]=cur.lastrowid
        for match in matches: conn.execute("INSERT INTO check_matches(check_id,restriction) VALUES (?,?)",(cur.lastrowid,match))
        conn.commit()
    except Exception:
        conn.rollback(); conn.close(); raise HTTPException(500,"Не удалось сохранить проверку: транзакция отменена")
    conn.close(); return record

@app.get("/api/stories", tags=["Истории"], summary="Получить истории для главной", description="Возвращает подписи, изображения и ссылки историй, которые отображаются в верхнем блоке главной страницы.")
def get_stories():
    result = rows("stories")
    conn = db(); recipes = {row["id"]: rowdict(row) for row in conn.execute("SELECT * FROM recipes")}; conn.close()
    images = {key: recipe["image"] for key, recipe in recipes.items()}
    for item in result:
        # The viewer shows a recipe story's dish right inside it, without another request.
        recipe = recipes.get(item.get("recipe_id")) if item.get("kind") == "recipe" else None
        item["recipe"] = {"id": recipe["id"], "title": recipe["title"], "description": recipe["description"], "ingredients": json.loads(recipe["ingredients"] or "[]"), "steps": json.loads(recipe["steps"] or "[]")} if recipe else None
        if item.get("recipe_id"): item["href"] = f"/recipe.html?id={item['recipe_id']}"
        # No own photo: the story shows its recipe's photo, so the cover always matches the dish.
        item["photo_source"] = "upload" if item["image"] else "recipe"
        if not item["image"]: item["image"] = images.get(item.get("recipe_id"), "story-01.jpg")
    return result
@app.get("/api/recipes/{recipe_id}", tags=["Рецепты"], summary="Получить рецепт", description="Возвращает ингредиенты, шаги приготовления и рекламную маркировку рецепта.")
def get_recipe(recipe_id: str):
    conn = db(); item = rowdict(conn.execute("SELECT * FROM recipes WHERE id=?", (recipe_id,)).fetchone()); conn.close()
    if not item: raise HTTPException(404, "Рецепт не найден")
    item["ingredients"] = json.loads(item["ingredients"] or "[]")
    item["steps"] = json.loads(item["steps"] or "[]")
    return item
@app.get("/api/recipes", tags=["Рецепты"], summary="Подобрать рецепты")
def get_recipes(exclude: str = ""):
    blocked = [x.strip().casefold() for x in exclude.split(",") if x.strip()]
    conn = db(); result = []
    for row in conn.execute("SELECT id,title,description,image,ingredients,sponsored_product,sponsored_label FROM recipes ORDER BY id"):
        item = dict(row); item["ingredients"] = json.loads(item["ingredients"] or "[]")
        source = " ".join(item["ingredients"]).casefold(); item["matches"] = [x for x in blocked if x in source]
        if not item["matches"]: result.append(item)
    conn.close(); return result
@app.get("/api/admin/recipes", tags=["Администрирование"], summary="Управление рецептами")
def admin_recipes(authorization: str | None = Header(default=None)):
    require_admin(authorization); return get_recipes("")
@app.post("/api/admin/recipes", tags=["Администрирование"], summary="Создать или изменить рецепт")
def save_recipe(data: RecipeData, authorization: str | None = Header(default=None)):
    require_admin(authorization); recipe_id = data.id or f"recipe-{secrets.token_hex(3)}"
    values = (recipe_id, data.title.strip(), data.description.strip(), data.image, json.dumps(data.ingredients, ensure_ascii=False), json.dumps(data.steps, ensure_ascii=False), data.sponsored_product.strip(), data.sponsored_label.strip())
    conn=db(); conn.execute("INSERT INTO recipes VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,description=excluded.description,image=excluded.image,ingredients=excluded.ingredients,steps=excluded.steps,sponsored_product=excluded.sponsored_product,sponsored_label=excluded.sponsored_label", values); conn.commit(); conn.close(); return {"id": recipe_id, **data.model_dump(exclude={"id"})}
@app.delete("/api/admin/recipes/{recipe_id}", tags=["Администрирование"], summary="Удалить рецепт")
def delete_recipe(recipe_id: str, authorization: str | None = Header(default=None)):
    require_admin(authorization); conn=db(); cur=conn.execute("DELETE FROM recipes WHERE id=?", (recipe_id,)); conn.commit(); conn.close()
    if not cur.rowcount: raise HTTPException(404, "Рецепт не найден")
    return {"deleted": recipe_id}
@app.get("/api/admin/users", tags=["Администрирование"], summary="Посмотреть список пользователей", description="Возвращает имена, логины, роли и количество проверок пользователей. Доступно только администратору.")
def admin_users(authorization: str | None = Header(default=None)):
    require_admin(authorization); conn=db(); result=[{**dict(x),"is_admin":bool(x["is_admin"])} for x in conn.execute("SELECT u.login,u.name,u.phone,u.is_admin,COUNT(c.id) checks_count FROM users u LEFT JOIN checks c ON c.login=u.login GROUP BY u.login")]; conn.close(); return result
@app.get("/api/admin/checks", tags=["Администрирование"], summary="Посмотреть все проверки", description="Возвращает общую историю проверок всех пользователей для административного просмотра.")
def admin_checks(authorization: str | None = Header(default=None)):
    require_admin(authorization); conn=db(); result=[]
    # Two JOINs: who checked (users) and what was checked (products).
    for x in conn.execute("""SELECT c.id, c.login, u.name AS user_name, c.product_id, COALESCE(p.name, c.product_name) AS product_name, p.category AS product_category,
            c.barcode, c.checked_at, c.result, c.reason, c.matches
        FROM checks c JOIN users u ON u.login = c.login LEFT JOIN products p ON p.id = c.product_id ORDER BY c.id"""):
        item=dict(x); item["matches"]=json.loads(item["matches"]); item["user"]=item.pop("login"); result.append(item)
    conn.close(); return result
@app.get("/api/admin/stories", tags=["Администрирование"], summary="Получить истории в админке", description="Возвращает полный список историй для редактирования в панели администратора.")
def admin_stories(authorization: str | None = Header(default=None)): require_admin(authorization); return get_stories()
@app.post("/api/admin/stories", tags=["Администрирование"], summary="Создать или изменить историю", description="Создаёт новую историю или обновляет существующую, если передан её идентификатор. Доступно только администратору.")
def save_story(data: StoryData, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    if data.id in ("story-how", "story-team"):
        raise HTTPException(403, "Системные истории нельзя изменять")
    data.recipe_id = data.recipe_id or None
    data.body = data.body.strip()
    if data.kind not in STORY_KINDS: raise HTTPException(400, "Выберите, что внутри истории: статья, рецепт или инструкция")
    if data.kind == "recipe" and not data.recipe_id: raise HTTPException(400, "Выберите рецепт для этой истории")
    if data.kind != "recipe" and not data.body: raise HTTPException(400, "Напишите текст статьи или шаги инструкции")
    if data.kind != "recipe": data.recipe_id = None
    if not data.image and not data.recipe_id: raise HTTPException(400, "Загрузите фото или выберите рецепт, чтобы взять фото из него")
    uploaded = re.fullmatch(r"uploads/[0-9a-f]{16}\.(jpg|png|webp)", data.image)
    if data.image and not (re.fullmatch(r"story-\d{2}\.jpg", data.image) or (uploaded and (UPLOADS / data.image[8:]).is_file())):
        raise HTTPException(400, "Некорректное изображение истории")
    if data.recipe_id:
        conn = db(); recipe_exists = conn.execute("SELECT 1 FROM recipes WHERE id=?", (data.recipe_id,)).fetchone(); conn.close()
        if not recipe_exists: raise HTTPException(404, "Выбранный рецепт не найден")
    story_href = f"/recipe.html?id={data.recipe_id}" if data.recipe_id else "/help.html"
    if data.id:
        conn=db(); item=rowdict(conn.execute("SELECT * FROM stories WHERE id=?",(data.id,)).fetchone()); conn.close()
        if not item: raise HTTPException(404, "История не найдена")
        changes = data.model_dump(); changes["href"] = story_href
        item.update(changes); conn=db(); conn.execute("UPDATE stories SET title=?,subtitle=?,image=?,href=?,recipe_id=?,kind=?,body=? WHERE id=?",(item["title"],item["subtitle"],item["image"],item["href"],item["recipe_id"],item["kind"],item["body"],data.id)); conn.commit(); conn.close(); return item
    item = {"id": f"story-{secrets.token_hex(3)}", **data.model_dump(exclude={"id"})}; item["href"] = story_href
    conn=db(); conn.execute("INSERT INTO stories(id,title,subtitle,image,href,recipe_id,kind,body) VALUES (:id,:title,:subtitle,:image,:href,:recipe_id,:kind,:body)", item); conn.commit(); conn.close(); return item
@app.post("/api/admin/uploads", tags=["Администрирование"], summary="Загрузить фото", description="Принимает изображение JPEG, PNG или WebP до 5 МБ в теле запроса и возвращает путь для поля image истории.")
async def upload_image(request: FastAPIRequest, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    data = await request.body()
    if not data: raise HTTPException(400, "Файл пустой")
    if len(data) > UPLOAD_MAX_BYTES: raise HTTPException(413, "Фото больше 5 МБ")
    ext = next((e for magic, e in UPLOAD_TYPES if data.startswith(magic) and (e != "webp" or data[8:12] == b"WEBP")), None)
    if not ext: raise HTTPException(415, "Подходят только фото JPEG, PNG или WebP")
    name = f"{secrets.token_hex(8)}.{ext}"
    (UPLOADS / name).write_bytes(data)
    return {"image": f"uploads/{name}"}
@app.delete("/api/admin/stories/{story_id}", tags=["Администрирование"], summary="Удалить историю", description="Удаляет историю главной страницы по идентификатору. Доступно только администратору.")
def delete_story(story_id: str, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    if story_id in ("story-how", "story-team"):
        raise HTTPException(403, "Системные истории нельзя удалять")
    conn=db(); item=rowdict(conn.execute("SELECT * FROM stories WHERE id=?",(story_id,)).fetchone())
    if item: conn.execute("DELETE FROM stories WHERE id=?",(story_id,)); conn.commit(); conn.close(); return {"deleted":item}
    conn.close()
    raise HTTPException(404, "История не найдена")

@app.get("/api/off/products/{barcode}", tags=["Open Food Facts"], summary="Найти продукт по штрихкоду", description="Запрашивает состав и сведения о продукте во внешнем сервисе Open Food Facts по штрихкоду.")
def off_product(barcode: str, fields: str = "product_name,product_name_ru,brands,quantity,ingredients_text,ingredients_text_ru,allergens,allergens_tags,additives_n,additives_tags,additives_original_tags,image_front_url,image_front_small_url"):
    try:
        req = Request(f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json?{urlencode({'fields': fields})}", headers={"User-Agent": "ISeeFoodAssistant/1.0"})
        with urlopen(req, timeout=12, context=TLS_CONTEXT) as response: return __import__('json').loads(response.read().decode())
    except Exception as exc: raise HTTPException(502, f"Open Food Facts недоступен: {exc}")

def openrouter_product_sources(message):
    sources = []
    for citation in message.get("annotations", []) or []:
        citation_url = citation.get("url_citation", {}) or {}
        url = citation_url.get("url")
        if url and url.startswith(("https://", "http://")):
            sources.append({"title": str(citation_url.get("title") or "Источник")[:180], "url": url})
    unique = []
    seen = set()
    for source in sources:
        if source["url"] not in seen:
            seen.add(source["url"])
            unique.append(source)
    return unique[:6]

def parse_model_json_content(message):
    """Parse JSON from OpenRouter message content across string/parts formats."""
    raw = message.get("content")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        content = "\n".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in raw
        )
    else:
        content = str(raw or "")
    content = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content, flags=re.IGNORECASE)
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Do not use a greedy regex: explanations can contain more than one brace
    # pair. Extract the first balanced JSON object, respecting quoted strings.
    start = content.find("{")
    while start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(content)):
            char = content[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(content[start:index + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break
        start = content.find("{", start + 1)
    raise ValueError("model response is not a JSON object")


def normalize_enrichment_fields(raw_fields):
    seen = set()
    return [field for field in raw_fields if field in AI_ENRICHMENT_FIELDS and not (field in seen or seen.add(field))]


def valid_enrichment_value(field, value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    normalized = value.casefold()
    if normalized in {"нет данных", "не найдено", "не указано", "unknown", "n/a", "null"}:
        return None
    if field == "nutrition" and not (re.search(r"\d", value) and re.search(r"(?:ккал|кдж|kcal|kj|\bг\b|\bмг\b|грамм)", normalized)):
        return None
    return value[:AI_FIELD_LIMITS[field]]


def validated_enrichment_fields(result, requested_fields):
    if not isinstance(result, dict):
        return {}
    return {
        field: value
        for field in requested_fields
        if (value := valid_enrichment_value(field, result.get(field))) is not None
    }


def build_product_enrichment_prompt(data, requested_fields, repair=False):
    # Keep prompts small enough for restricted OpenRouter keys. Never send the
    # full product database payload back to the model; it is usually much
    # larger than the identity fields and does not improve web search.
    identity = " ".join(part.strip() for part in (data.brand, data.name, data.country) if part and part.strip())[:240]
    labels = {"ingredients": "состав", "allergens": "аллергены", "additives": "добавки", "nutrition": "пищевая ценность", "product_info": "краткие сведения", "product_name": "название"}
    rules = "Ищи именно этот продукт. Не угадывай состав или аллергены. Верни только JSON с запрошенными ключами; неизвестное значение — null. Не включай ссылки и объяснения."
    if repair:
        rules += " Это повторный поиск: эти поля не нашлись в прошлый раз. Проверь сайт производителя, магазинов и фото упаковки."
    return {
        "product": identity,
        "barcode": data.barcode.strip(),
        "fields_to_find": list(requested_fields),
        "labels": {field: labels[field] for field in requested_fields},
        "rules": rules,
    }


def request_openrouter_product_details(api_key, prompt, model=None, web_results=None):
    if web_results is None:
        web_results = int(os.getenv("OPENROUTER_WEB_RESULTS", "3"))
    request_body = {
        # Avoid the rotating free-model pool: providers differ in web-tool and
        # JSON support. Use one consistent model by default.
        "model": model or os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": "Извлеки только проверяемые данные об указанном продукте. Не угадывай. Верни только компактный JSON."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        # Keep the default compact: low-credit keys can reject a request before
        # inference when max_tokens is larger than the remaining allowance.
        "max_tokens": max(128, min(int(os.getenv("OPENROUTER_MAX_TOKENS", "220")), 1000)),
        "response_format": {"type": "json_object"},
        # OpenRouter web plugin: the model answers from fresh search results
        # instead of its own memory; citations come back in message.annotations.
        # Each result adds roughly 400 prompt tokens, so keep the default small.
        "plugins": [{"id": "web", "max_results": max(1, web_results)}],
    }
    request = Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(request_body).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "http://127.0.0.1:4173", "X-Title": "I-See Food Assistant"}, method="POST")
    try:
        with urlopen(request, timeout=35, context=TLS_CONTEXT) as response:
            upstream = json.loads(response.read().decode())
    except HTTPError as error:
        try:
            provider_body = json.loads(error.read().decode("utf-8", errors="replace"))
            provider_message = str((provider_body.get("error") or {}).get("message") or provider_body.get("message") or "").strip()
        except Exception:
            provider_message = ""
        print(f"OpenRouter product-details error: HTTP {error.code}; {provider_message or 'без текста от провайдера'}", flush=True)
        if error.code == 403:
            raise HTTPException(403, "MODEL_ACCESS_DENIED")
        if error.code == 429:
            raise HTTPException(503, "OpenRouter: превышен лимит запросов. Проверьте лимиты аккаунта и повторите позже.")
        if error.code == 402 and "prompt tokens limit" in provider_message.lower():
            # The key's remaining budget cannot fit this prompt; callers retry with fewer web results.
            raise HTTPException(402, "PROMPT_TOKEN_LIMIT")
        if error.code == 402:
            raise HTTPException(503,"OpenRouter: для выбранной модели или веб-поиска недостаточно средств/кредитов. Проверьте баланс и лимиты аккаунта.")
        if error.code in (401, 403):
            suffix = f" Причина OpenRouter: {provider_message[:180]}" if provider_message else ""
            raise HTTPException(503, "OpenRouter отклонил запрос. Проверьте OPENROUTER_API_KEY и доступ к модели." + suffix)
        detail = f"OpenRouter вернул HTTP {error.code}"
        if provider_message:
            detail += f": {provider_message[:220]}"
        raise HTTPException(502, detail)
    except (URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        print(f"OpenRouter product-details connection error: {type(reason).__name__}: {reason}", flush=True)
        raise HTTPException(502, "Не удалось связаться с OpenRouter. Проверьте интернет-соединение backend-сервера.")
    except json.JSONDecodeError:
        raise HTTPException(502, "OpenRouter вернул некорректный JSON-ответ.")
    try:
        message = upstream["choices"][0]["message"]
        result = parse_model_json_content(message)
        result["sources"] = openrouter_product_sources(message)
        return result
    except (KeyError, IndexError, TypeError, ValueError):
        choices = upstream.get("choices") or []
        finish_reason = choices[0].get("finish_reason", "неизвестно") if choices else "нет choices"
        failed_message = choices[0].get("message", {}) if choices else {}
        raw_content = failed_message.get("content", "") if isinstance(failed_message, dict) else ""
        if isinstance(raw_content, list):
            raw_content = " ".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in raw_content)
        content_preview = re.sub(r"\s+", " ", str(raw_content))[:500]
        print(f"OpenRouter product-details: unreadable response; finish_reason={finish_reason}; message_keys={sorted(failed_message.keys()) if isinstance(failed_message, dict) else []}; preview={content_preview!r}", flush=True)
        raise HTTPException(502, f"Модель вернула неструктурированный ответ (finish_reason: {finish_reason}). Попробуйте ещё раз; подробность есть в консоли backend.")


def gemini_product_sources(candidate):
    """Web pages Google Search grounding actually used for the answer."""
    sources = []
    for chunk in (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []:
        web = chunk.get("web") or {}
        url = web.get("uri")
        if url and url.startswith(("https://", "http://")):
            sources.append({"title": str(web.get("title") or "Источник")[:180], "url": url})
    return list({source["url"]: source for source in sources}.values())[:6]


def request_gemini_product_details(api_key, prompt):
    """Ask Gemini with Google Search grounding; free tier keys come from Google AI Studio."""
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    request_body = {
        "systemInstruction": {"parts": [{"text": "Найди указанный продукт через поиск Google (по штрихкоду и названию) и извлеки только то, что написано на страницах производителя или магазинов. Не угадывай. Ответь одним JSON-объектом с ключами из fields_to_find; неизвестное значение — null."}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(prompt, ensure_ascii=False)}]}],
        # Structured output is not combined with the search tool here,
        # so JSON is requested in the prompt and parsed leniently.
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
    }
    request = Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", data=json.dumps(request_body).encode(), headers={"x-goog-api-key": api_key, "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=40, context=TLS_CONTEXT) as response:
            upstream = json.loads(response.read().decode())
    except HTTPError as error:
        try:
            provider_body = json.loads(error.read().decode("utf-8", errors="replace"))
            provider_message = str((provider_body.get("error") or {}).get("message") or "").strip()
        except Exception:
            provider_message = ""
        print(f"Gemini product-details error: HTTP {error.code}; {provider_message or 'без текста от провайдера'}", flush=True)
        if error.code == 429:
            raise HTTPException(503, "Gemini: исчерпан бесплатный дневной лимит. Повторите завтра.")
        if "location is not supported" in provider_message.lower():
            raise HTTPException(503, "Gemini недоступен из страны, где запущен сервер.")
        if error.code in (400, 401, 403):
            raise HTTPException(503, "Gemini отклонил запрос. Проверьте GEMINI_API_KEY.")
        raise HTTPException(502, f"Gemini вернул HTTP {error.code}")
    except (URLError, TimeoutError, OSError) as error:
        print(f"Gemini product-details connection error: {getattr(error, 'reason', error)}", flush=True)
        raise HTTPException(502, "Не удалось связаться с Gemini.")
    except json.JSONDecodeError:
        raise HTTPException(502, "Gemini вернул некорректный JSON-ответ.")
    try:
        candidate = upstream["candidates"][0]
        text = "".join(part.get("text", "") for part in candidate["content"]["parts"])
        result = parse_model_json_content({"content": text})
    except (KeyError, IndexError, TypeError, ValueError):
        print(f"Gemini product-details: unreadable response; preview={json.dumps(upstream, ensure_ascii=False)[:500]!r}", flush=True)
        raise HTTPException(502, "Gemini вернул неструктурированный ответ.")
    result["sources"] = gemini_product_sources(candidate)
    if not result["sources"]:
        # Without grounding the model answered from memory; for allergens that is not acceptable.
        print("Gemini product-details: answer had no search sources; discarded", flush=True)
        return {"sources": []}
    return result


def ai_providers():
    """Providers in priority order as (name, fetch(data, fields, repair), retries, max_fields).

    The free barcode search goes first; Gemini and paid OpenRouter web search only
    fill what it left empty, two fields at a time to keep their prompts small.
    """
    providers = []
    if os.getenv("FREE_SEARCH", "1") != "0":
        def free(data, fields, repair):
            try:
                return free_search.lookup(data, fields)
            except free_search.SearchUnavailable as error:
                raise HTTPException(503, str(error))
        # It ignores fields it cannot read from a label, so it gets the whole list.
        providers.append(("Бесплатный поиск", free, False, len(AI_ENRICHMENT_FIELDS)))
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        providers.append(("Gemini + Google Search", lambda data, fields, repair: request_gemini_product_details(gemini_key, build_product_enrichment_prompt(data, fields, repair)), True, 2))
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if openrouter_key and os.getenv("OPENROUTER_WEB_SEARCH", "1") != "0":
        def openrouter(data, fields, repair):
            prompt = build_product_enrichment_prompt(data, fields, repair)
            try:
                return request_openrouter_product_details(openrouter_key, prompt)
            except HTTPException as error:
                if error.status_code == 402:
                    print("OpenRouter prompt exceeds the key's remaining limit; retrying with one web result", flush=True)
                    try:
                        return request_openrouter_product_details(openrouter_key, prompt, web_results=1)
                    except HTTPException as retry_error:
                        if retry_error.status_code == 402:
                            raise HTTPException(503, "OpenRouter: у API-ключа почти исчерпан лимит. Увеличьте лимит ключа или пополните баланс в OpenRouter.")
                        raise
                if error.status_code != 403:
                    raise
                fallback = os.getenv("OPENROUTER_FALLBACK_MODEL", "google/gemini-2.0-flash-001")
                print(f"OpenRouter primary model denied; retrying with {fallback}", flush=True)
                return request_openrouter_product_details(openrouter_key, prompt, fallback)
        providers.append(("OpenRouter + web search", openrouter, True, 2))
    return providers


def read_ai_cache(cache_key):
    conn = db()
    try:
        row = conn.execute("SELECT response FROM ai_cache WHERE cache_key=? AND expires_at>?", (cache_key, int(time.time()))).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row else None

def write_ai_cache(cache_key, response_data):
    conn = db()
    try:
        conn.execute("INSERT INTO ai_cache(cache_key,response,expires_at) VALUES (?,?,?) ON CONFLICT(cache_key) DO UPDATE SET response=excluded.response, expires_at=excluded.expires_at", (cache_key, json.dumps(response_data, ensure_ascii=False), int(time.time()) + AI_CACHE_SECONDS))
        conn.commit()
    finally:
        conn.close()

def clear_ai_cache():
    conn = db(); conn.execute("DELETE FROM ai_cache"); conn.commit(); conn.close()


@app.post("/api/ai/product-details", tags=["Поиск состава с ИИ"], summary="Найти недостающий состав и аллергены", description="Бесплатно ищет страницы товара по штрихкоду и извлекает с них состав, аллергены, добавки и пищевую ценность; незаполненное дополняют Gemini или OpenRouter с веб-поиском, если они настроены. Принимаются только значения, найденные на страницах; результат кэшируется в базе.")
def ai_product_details(data: ProductLookupData, request: FastAPIRequest):
    providers = ai_providers()
    if not providers:
        return {"provider": None, "matched": False, "fields": {}, "requested": data.missing, "missing": data.missing, "sources": [], "confidence": "low", "match_reason": "AI is not configured"}
    requested = normalize_enrichment_fields(data.missing)
    if not requested:
        raise HTTPException(400, "Не указаны поля для поиска")
    priority = ["ingredients", "allergens", "product_name", "additives", "nutrition", "product_info"]
    requested = [field for field in priority if field in requested]
    cache_key = (data.barcode.strip() or f"{data.brand.strip()}:{data.name.strip()}").casefold() + ":" + ",".join(sorted(requested))
    cached = read_ai_cache(cache_key)
    if cached:
        if cached["fields"].get("allergens"):
            cached["fields"]["allergens"] = free_search.russian_allergens(cached["fields"]["allergens"])
        return cached
    now = time.time()
    with ai_lock:
        client_ip = request.client.host if request.client else "unknown"
        recent = [stamp for stamp in ai_request_times.get(client_ip, []) if stamp > now - 3600]
        if len(recent) >= 12:
            raise HTTPException(429, "Достигнут лимит поиска ИИ с этого подключения. Повторите позже.")
        recent.append(now)
        ai_request_times[client_ip] = recent

    fields = {}
    sources = []
    first_result = {}
    used = []
    for name, fetch, retries, max_fields in providers:
        unresolved = [field for field in requested if field not in fields][:max_fields]
        if not unresolved or provider_cooldown.get(name, 0) > time.time():
            continue
        try:
            result = fetch(data, unresolved, False)
            found = validated_enrichment_fields(result, unresolved)
            if found:
                first_result = first_result or result
                used.append(name)
                fields.update(found)
                sources += result.get("sources") or []
            still = [field for field in unresolved if field not in found]
            if still and retries:
                # One targeted retry only for the fields this search left empty.
                retry_result = fetch(data, still, True)
                found = validated_enrichment_fields(retry_result, still)
                if found and name not in used:
                    used.append(name)
                fields.update(found)
                if found:
                    sources += retry_result.get("sources") or []
        except HTTPException as error:
            # Enrichment is optional: quota, network and provider errors fall through
            # to the next provider and never break a successful barcode lookup.
            print(f"{name} enrichment skipped: HTTP {error.status_code}; {error.detail}", flush=True)
            if retries and error.status_code == 503:
                # Quota, credits or location will not change in the next minutes.
                provider_cooldown[name] = time.time() + PROVIDER_COOLDOWN_SECONDS
    if fields.get("allergens"):
        fields["allergens"] = free_search.russian_allergens(fields["allergens"])
    unresolved = [field for field in requested if field not in fields]
    accepted = bool(fields)
    sources = list({source["url"]: source for source in sources}.values())[:6]

    response_data = {
        "provider": " / ".join(used) or None,
        "matched": accepted,
        "fields": fields,
        "requested": requested,
        "missing": unresolved,
        "sources": sources,
        "confidence": first_result.get("confidence", "medium") if accepted else "low",
        "match_reason": str(first_result.get("match_reason") or "")[:400],
    }
    print(f"AI product-details result: provider={response_data['provider']}; fields={sorted(fields)}; missing={unresolved}", flush=True)
    # Do not cache a wholly empty response: the web index may have changed by the next scan.
    if accepted:
        write_ai_cache(cache_key, response_data)
    return response_data

@app.get("/api/stores", tags=["Магазины"], summary="Найти магазины рядом", description="Ищет продуктовые магазины в радиусе 2 километров от переданных координат через OpenStreetMap.")
def stores(lat: float = Query(...), lon: float = Query(...)):
    query = '[out:json][timeout:20];(nwr["shop"~"^(supermarket|convenience|greengrocer|bakery|department_store)$"]' + f'(around:{STORE_RADIUS_METERS},{lat},{lon}););out center tags;'
    deadline = time.monotonic() + 32
    def fetch(provider):
        # Busy mirrors answer 429/504 at once, so retry them until the shared deadline.
        while True:
            try:
                req = Request(provider, data=urlencode({"data": query}).encode(), headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ISeeFoodAssistant/1.0"}, method="POST")
                with urlopen(req, timeout=max(1, deadline - time.monotonic()), context=TLS_CONTEXT) as response:
                    data = json.loads(response.read().decode())
                if isinstance(data.get("elements"), list) and not data.get("remark"): return data
            except Exception: pass
            if deadline - time.monotonic() < 3: return None
            time.sleep(1)
    pool = ThreadPoolExecutor(len(STORE_PROVIDERS))
    try:
        for future in as_completed([pool.submit(fetch, provider) for provider in STORE_PROVIDERS]):
            if future.result(): return future.result()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    raise HTTPException(503, "Сервисы магазинов временно недоступны")

# Озвучка нейросетевыми голосами Microsoft (без ключа); браузерный голос — запасной вариант на странице.
TTS_VOICES = {"female": "ru-RU-SvetlanaNeural", "male": "ru-RU-DmitryNeural"}
TTS_CACHE = DB_PATH.parent / "tts"
class SpeechData(BaseModel): text: str = Field(min_length=1, max_length=4000); voice: str = "female"
@app.post("/api/tts", tags=["Озвучка"], summary="Озвучить текст", description="Возвращает MP3 с текстом, прочитанным естественным русским голосом. Готовые файлы кэшируются.")
async def tts(data: SpeechData):
    try: import edge_tts
    except ImportError: raise HTTPException(503, "Озвучка не установлена: pip install edge-tts")
    voice = TTS_VOICES.get(data.voice, TTS_VOICES["female"])
    target = TTS_CACHE / f"{hashlib.sha256(f'{voice}|{data.text}'.encode()).hexdigest()}.mp3"
    if not target.is_file():
        audio = bytearray()
        try:
            # Slightly slower than default: the page is read for older people.
            async for chunk in edge_tts.Communicate(data.text, voice, rate="-8%").stream():
                if chunk["type"] == "audio": audio.extend(chunk["data"])
        except Exception as error:
            print(f"TTS failed: {error}", flush=True)
            raise HTTPException(503, "Сервис озвучки временно недоступен")
        if not audio: raise HTTPException(503, "Сервис озвучки вернул пустой ответ")
        TTS_CACHE.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio)
    return Response(target.read_bytes(), media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400"})

# HTML pages are revalidated on every visit so layout changes reach users at once.
PAGE_HEADERS = {"Cache-Control": "no-cache"}
@app.get("/favicon.ico", include_in_schema=False)
def favicon(): return FileResponse(ASSETS / "images" / "favicon.png", media_type="image/png")
@app.get("/", include_in_schema=False)
def index(): return FileResponse(PAGES / "index.html", headers=PAGE_HEADERS)
@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def admin_page(): return FileResponse(PAGES / "admin.html", headers=PAGE_HEADERS)
@app.get("/{page}.html", include_in_schema=False)
def page(page: str):
    target = PAGES / f"{page}.html"
    if not target.is_file(): raise HTTPException(404, "Страница не найдена")
    return FileResponse(target, headers=PAGE_HEADERS)
app.mount("/assets/images/uploads", StaticFiles(directory=UPLOADS), name="uploads")
app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "4173")), reload=False)
