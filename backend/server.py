#!/usr/bin/env python3
"""FastAPI backend for the I-See project.

Run with: uvicorn backend.server:app --host 127.0.0.1 --port 4173 --reload
Swagger UI: /docs
"""
import json, os, re, secrets, threading, time, sqlite3, shutil, subprocess
import ssl
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import certifi

from fastapi import FastAPI, HTTPException, Header, Query, Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent.parent
PAGES = BASE / "frontend" / "pages"
ASSETS = BASE / "frontend" / "assets"
STORE_RADIUS_METERS = 2000
STORE_PROVIDERS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter")
DB_PATH = Path(os.getenv("DATABASE_PATH", BASE / "data" / "isee.sqlite3"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())

tokens = {}
lock = threading.RLock()
ai_enrichment_cache = {}
ai_request_times = {}
ai_lock = threading.Lock()
AI_ENRICHMENT_FIELDS = ("product_name", "ingredients", "allergens", "additives", "product_info", "nutrition")
AI_FIELD_LIMITS = {"product_name": 180, "ingredients": 4000, "allergens": 1000, "additives": 1000, "product_info": 1800, "nutrition": 1800}

def db():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (login TEXT PRIMARY KEY, password TEXT NOT NULL, name TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL, barcode TEXT NOT NULL DEFAULT '', ingredients TEXT NOT NULL DEFAULT '', allergens TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS profiles (login TEXT PRIMARY KEY REFERENCES users(login) ON DELETE CASCADE, restrictions TEXT NOT NULL DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS checks (id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT NOT NULL REFERENCES users(login), product_id INTEGER REFERENCES products(id) ON DELETE SET NULL, product_name TEXT NOT NULL, barcode TEXT NOT NULL DEFAULT '', checked_at TEXT NOT NULL, result TEXT NOT NULL, reason TEXT, matches TEXT NOT NULL DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS check_matches (check_id INTEGER NOT NULL REFERENCES checks(id) ON DELETE CASCADE, restriction TEXT NOT NULL, PRIMARY KEY(check_id, restriction));
    CREATE TABLE IF NOT EXISTS stories (id TEXT PRIMARY KEY, title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '', image TEXT NOT NULL, href TEXT NOT NULL DEFAULT 'help.html');
    CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
    CREATE INDEX IF NOT EXISTS idx_checks_login_date ON checks(login, checked_at);
    CREATE INDEX IF NOT EXISTS idx_check_matches_restriction ON check_matches(restriction);
    """)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.executemany("INSERT INTO users VALUES (?,?,?,?)", [("user","qwerty","Пользователь",0),("admin","12345","Администратор",1)])
        conn.executemany("INSERT INTO profiles VALUES (?,?)", [("user","[]"),("admin","[]")])
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        conn.executemany("INSERT INTO products(name,category,barcode,ingredients,allergens,price) VALUES (?,?,?,?,?,?)", [("Йогурт клубничный","Молочные продукты","4601234567890","молоко, клубника, сахар","молоко",89),("Хлеб пшеничный","Выпечка","4601234567891","пшеничная мука, вода, дрожжи","пшеница, глютен",65),("Шоколад с орехами","Сладости","4601234567892","какао, сахар, фундук, молоко","фундук, орехи, молоко",149)])
    if conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 0:
        rows = [(f"story-{i:02d}",t,s,f"story-{i:02d}.jpg",h) for i,(t,s,h) in enumerate((("Новый образ","Детали и настроение","help.html"),("Город не спит","Вечерние огни","help.html"),("Тёплый вечер","Моменты на память","medical-card.html"),("Wanna play?","Новая игра","feedback.html"),("Особенный день","Важные события","help.html"),("Вечер дома","Время для себя","help.html"),("Другой взгляд","Игра света и тени","help.html")),1)]
        conn.executemany("INSERT INTO stories VALUES (?,?,?,?,?)", rows)
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
class ProductData(BaseModel):
    name: str = Field(min_length=1, max_length=120); category: str = "Продукты"; barcode: str = ""; ingredients: str = ""; allergens: str = ""; price: int = Field(default=0, ge=0, le=10000000)
class ProfileData(BaseModel): restrictions: list[dict] = Field(default_factory=list, max_length=100)
class CheckData(BaseModel): product_id: int | None = None; product: dict | None = None
class StoryData(BaseModel): id: str = ""; title: str = Field(min_length=1, max_length=60); subtitle: str = ""; image: str; href: str = "help.html"
class ProductLookupData(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    brand: str = Field(default="", max_length=120)
    barcode: str = Field(default="", max_length=32)
    country: str = Field(default="Россия", max_length=80)
    missing: list[str] = Field(default_factory=lambda: ["ingredients", "allergens", "product_info", "nutrition", "additives"], max_length=5)
    known_data: dict = Field(default_factory=dict)

def user_from_token(authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "): return None
    return tokens.get(authorization.split(" ", 1)[1].strip())
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
@app.post("/api/login", tags=["Авторизация"], summary="Войти в аккаунт", description="Проверяет логин и пароль, после чего выдаёт bearer-токен для защищённых запросов.")
def login(data: LoginData):
    conn=db(); account=rowdict(conn.execute("SELECT * FROM users WHERE login=?", (data.login.strip(),)).fetchone()); conn.close()
    if not account or not secrets.compare_digest(data.password, account["password"]): raise HTTPException(401, "Неверный логин или пароль")
    token = secrets.token_urlsafe(24); tokens[token] = data.login.strip()
    return {"token": token, "user": {"login": data.login.strip(), "name": account["name"], "is_admin": bool(account["is_admin"])} }

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
    user = require_user(authorization); clean = []
    for item in data.restrictions:
        if isinstance(item, dict) and item.get("type") in ("allergy", "avoid") and str(item.get("name", "")).strip(): clean.append({"type": item["type"], "name": str(item["name"]).strip()[:80]})
    conn=db(); conn.execute("INSERT INTO profiles(login,restrictions) VALUES (?,?) ON CONFLICT(login) DO UPDATE SET restrictions=excluded.restrictions",(user,json.dumps(clean,ensure_ascii=False))); conn.commit(); conn.close(); return {"restrictions": clean}
@app.get("/api/checks", tags=["Профиль и проверки"], summary="Получить историю проверок", description="Возвращает только проверки текущего авторизованного пользователя, отсортированные в порядке сохранения.")
def get_checks(authorization: str | None = Header(default=None)):
    user = require_user(authorization); conn=db(); result=[]
    for x in conn.execute("SELECT c.*, p.name AS product_name_joined FROM checks c LEFT JOIN products p ON p.id=c.product_id WHERE c.login=? ORDER BY c.id",(user,)):
        item=dict(x); item["user"]=item.pop("login"); item["matches"]=json.loads(item["matches"]); item.pop("product_name_joined",None); result.append(item)
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
def get_stories(): return rows("stories")
@app.get("/api/admin/users", tags=["Администрирование"], summary="Посмотреть список пользователей", description="Возвращает имена, логины, роли и количество проверок пользователей. Доступно только администратору.")
def admin_users(authorization: str | None = Header(default=None)):
    require_admin(authorization); conn=db(); result=[{**dict(x),"is_admin":bool(x["is_admin"])} for x in conn.execute("SELECT u.login,u.name,u.is_admin,COUNT(c.id) checks_count FROM users u LEFT JOIN checks c ON c.login=u.login GROUP BY u.login")]; conn.close(); return result
@app.get("/api/admin/checks", tags=["Администрирование"], summary="Посмотреть все проверки", description="Возвращает общую историю проверок всех пользователей для административного просмотра.")
def admin_checks(authorization: str | None = Header(default=None)):
    require_admin(authorization); conn=db(); result=[]
    for x in conn.execute("SELECT * FROM checks ORDER BY id"):
        item=dict(x); item["matches"]=json.loads(item["matches"]); item["user"]=item.pop("login"); result.append(item)
    conn.close(); return result
@app.get("/api/admin/stories", tags=["Администрирование"], summary="Получить истории в админке", description="Возвращает полный список историй для редактирования в панели администратора.")
def admin_stories(authorization: str | None = Header(default=None)): require_admin(authorization); return rows("stories")
@app.post("/api/admin/stories", tags=["Администрирование"], summary="Создать или изменить историю", description="Создаёт новую историю или обновляет существующую, если передан её идентификатор. Доступно только администратору.")
def save_story(data: StoryData, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    if not re.fullmatch(r"story-\d{2}\.jpg", data.image) or not re.fullmatch(r"(?:[a-zA-Z0-9-]+\.html|/)", data.href): raise HTTPException(400, "Некорректные данные истории")
    if data.id:
        conn=db(); item=rowdict(conn.execute("SELECT * FROM stories WHERE id=?",(data.id,)).fetchone()); conn.close()
        if not item: raise HTTPException(404, "История не найдена")
        item.update(data.model_dump()); conn=db(); conn.execute("UPDATE stories SET title=?,subtitle=?,image=?,href=? WHERE id=?",(item["title"],item["subtitle"],item["image"],item["href"],data.id)); conn.commit(); conn.close(); return item
    item = {"id": f"story-{secrets.token_hex(3)}", **data.model_dump(exclude={"id"})}; conn=db(); conn.execute("INSERT INTO stories VALUES (?,?,?,?,?)",tuple(item.values())); conn.commit(); conn.close(); return item
@app.delete("/api/admin/stories/{story_id}", tags=["Администрирование"], summary="Удалить историю", description="Удаляет историю главной страницы по идентификатору. Доступно только администратору.")
def delete_story(story_id: str, authorization: str | None = Header(default=None)):
    require_admin(authorization)
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
    field_definitions = {
        "product_name": "Исправленное и нормально оформленное название товара на русском: правильный регистр и орфография, узнаваемый бренд, тип продукта, вкус/вариант и объём, если они подтверждены. Не пиши всё заглавными буквами и не добавляй выдуманных характеристик.",
        "ingredients": "Полный состав в исходном порядке с упаковки: ингредиенты, компоненты и их доли, если они указаны. Не сокращай перечень и не пересказывай его.",
        "allergens": "Только аллергены, явно обозначенные для этого продукта: «содержит», «может содержать следы» или аналогичная формулировка. Не выводи аллергены по ингредиентам и не добавляй предположения.",
        "additives": "Только пищевые добавки, явно перечисленные в составе: название и E-код, если он указан. Не относись к обычным ингредиентам как к добавкам и не придумывай E-коды.",
        "product_info": "Короткая фактическая справка: категория товара, вид, вкус/вариант, назначение или способ употребления, объём/масса и важные особенности только тогда, когда они подтверждены источником.",
        "nutrition": "Пищевая и энергетическая ценность строго на 100 г или 100 мл: ккал/кДж, белки, жиры, углеводы, сахар, соль и другие показатели, только если они приведены на упаковке или в карточке товара. Сохраняй точные числа и единицы.",
    }
    return {
        "task": "Найди и извлеки только запрошенные сведения об одном пищевом продукте. Ищи прежде всего по бренду, названию и вкусу/разновидности; различия в объёме, дизайне упаковки или несущественных формулировках названия не делают источник неподходящим. Не возвращай поисковую выдачу, ссылки или данные явно другого продукта.",
        # Deliberately omit the barcode: enrichment is searched by the human
        # readable product identity only (name, brand, variant and volume).
        "product": {"name": data.name.strip(), "brand": data.brand.strip(), "market": data.country.strip()},
        "already_known_from_product_database": data.known_data,
        "fields_to_find": requested_fields,
        "field_definitions": {field: field_definitions[field] for field in requested_fields},
        "requirements": [
            "Ищи только поля из fields_to_find. Для каждого запрошенного поля выполни отдельную проверку в источниках; поля, которые не запрошены, верни null.",
            "Формируй запросы из бренда, полного названия, вкуса/варианта, объёма и рынка. Штрихкод не используй ни в запросах, ни как обязательное условие совпадения.",
            "Приоритет источников: официальный сайт бренда/производителя и фотография маркировки, затем карточка крупного магазина или проверенная продуктовая база. Поисковый сниппет не является источником данных.",
            "Сопоставляй прежде всего бренд, тип товара, вкус/вариант и рынок. Разный объём, дизайн упаковки или сокращённое название допустимы, если это явно та же линейка и разновидность; не используй сведения только когда это другой вкус, иной вид товара или другой бренд.",
            "Текст для ingredients, allergens, additives и nutrition извлекай дословно или с минимальным форматированием. Не вычисляй и не дополняй отсутствующие значения.",
            "Для nutrition недостаточно сообщить, что таблица есть в источнике: верни саму пищевую ценность с числом и единицей либо null.",
            "Для product_info разрешено только нейтральное описание из подтверждённых свойств. Не добавляй рекламные обещания, медицинские выводы и неподтверждённые характеристики.",
            "Не переписывай сведения из already_known_from_product_database: ищи только недостающие поля. Когда запрошенное поле не найдено после целевого поиска, верни null, а не фразу об отсутствии данных.",
            "Верни только валидный JSON со ВСЕМИ запрошенными ключами, включая product_name, если он запрошен. Название оформи в обычном читаемом регистре, например «Сок J7 яблочный осветлённый, 0,85 л», а не капслоком. Остальные поля: ingredients, allergens, additives, product_info, nutrition; неизвестные значения верни null. Добавь confidence и match_reason без URL и названий сайтов.",
            "Не включай в JSON ссылки, URL, названия сайтов, цитаты и список результатов поиска.",
        ] + (["Это повторный поиск: верни фактические значения только для ещё незаполненных полей. Не заменяй значение описанием источника, причиной совпадения или фразой о том, что данные доступны."] if repair else []),
    }


def request_openrouter_product_details(api_key, prompt):
    request_body = {
        # Avoid the rotating free-model pool: providers differ in web-tool and
        # JSON support. Use one consistent model by default.
        "model": os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini"),
        "messages": [
            {"role": "system", "content": "Ты аккуратный помощник по поиску маркировки продуктов. Твоя задача — вернуть заполненную карточку продукта, а не список сайтов. Ищи и заполняй все запрошенные поля: состав, аллергены, добавки, пищевую ценность и дополнительную информацию. Точность важнее полноты: никогда не угадывай состав, аллергены или цифры пищевой ценности. Верни только JSON."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        # Keep below the smallest credit budget reported by OpenRouter for
        # this workspace/key so the request is not rejected before inference.
        "max_tokens": 1000,
        "response_format": {"type": "json_object"},
        "plugins": [{"id": "web", "engine": "exa", "max_results": 3}],
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
        if error.code == 429:
            raise HTTPException(503, "OpenRouter: превышен лимит запросов. Проверьте лимиты аккаунта и повторите позже.")
        if error.code == 402:
            raise HTTPException(503, "OpenRouter: для выбранной модели или веб-поиска недостаточно средств/кредитов. Проверьте баланс и лимиты аккаунта.")
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
        return parse_model_json_content(message)
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


@app.post("/api/ai/product-details", tags=["Поиск состава с ИИ"], summary="Найти недостающий состав и аллергены", description="Ищет сведения о продукте через OpenRouter с веб-поиском. Заполняет только подтверждённые источниками поля; результат может быть частичным, а список missing содержит недоступные после поиска поля.")
def ai_product_details(data: ProductLookupData, request: FastAPIRequest):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(503, "AI_NOT_CONFIGURED: добавьте OPENROUTER_API_KEY в окружение backend")
    requested = normalize_enrichment_fields(data.missing)
    if not requested:
        raise HTTPException(400, "Не указаны поля для поиска")
    cache_key = (data.barcode.strip() or f"{data.brand.strip()}:{data.name.strip()}").casefold() + ":" + ",".join(sorted(requested))
    now = time.time()
    with ai_lock:
        cached = ai_enrichment_cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]
        if cached:
            ai_enrichment_cache.pop(cache_key, None)
        client_ip = request.client.host if request.client else "unknown"
        recent = [stamp for stamp in ai_request_times.get(client_ip, []) if stamp > now - 3600]
        if len(recent) >= 12:
            raise HTTPException(429, "Достигнут лимит поиска ИИ с этого подключения. Повторите позже.")
        recent.append(now)
        ai_request_times[client_ip] = recent

    fields = {}
    first_result = request_openrouter_product_details(api_key, build_product_enrichment_prompt(data, requested))
    fields.update(validated_enrichment_fields(first_result, requested))
    unresolved = [field for field in requested if field not in fields]
    retry_error = None
    if unresolved and not fields:
        try:
            retry_result = request_openrouter_product_details(
                api_key,
                build_product_enrichment_prompt(data, unresolved, repair=True),
            )
            fields.update(validated_enrichment_fields(retry_result, unresolved))
        except HTTPException as error:
            # A successful first search remains useful even if the focused retry
            # is temporarily unavailable.
            retry_error = error
    unresolved = [field for field in requested if field not in fields]
    accepted = bool(fields)
    if not accepted and retry_error:
        raise retry_error

    response_data = {
        "provider": "OpenRouter + web search",
        "matched": accepted,
        "fields": fields,
        "requested": requested,
        "missing": unresolved,
        "confidence": first_result.get("confidence", "medium") if accepted else "low",
        "match_reason": str(first_result.get("match_reason") or "")[:400],
    }
    print(f"OpenRouter product-details result: fields={sorted(fields)}; missing={unresolved}", flush=True)
    # Do not cache a wholly empty response: the web index may have changed by
    # the next scan. Cache valid partial results along with their missing fields.
    if accepted:
        with ai_lock:
            ai_enrichment_cache[cache_key] = (time.time() + 3600, response_data)
    return response_data

@app.get("/api/stores", tags=["Магазины"], summary="Найти магазины рядом", description="Ищет продуктовые магазины в радиусе 2 километров от переданных координат через OpenStreetMap.")
def stores(lat: float = Query(...), lon: float = Query(...)):
    query = '[out:json][timeout:20];(nwr["shop"~"^(supermarket|convenience|greengrocer|bakery|department_store)$"]' + f'(around:{STORE_RADIUS_METERS},{lat},{lon}););out center tags;'
    for provider in STORE_PROVIDERS:
        try:
            req = Request(provider, data=urlencode({"data": query}).encode(), headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ISeeFoodAssistant/1.0"}, method="POST")
            with urlopen(req, timeout=13, context=TLS_CONTEXT) as response: return __import__('json').loads(response.read().decode())
        except Exception: continue
    raise HTTPException(503, "Сервисы магазинов временно недоступны")

@app.get("/", include_in_schema=False)
def index(): return FileResponse(PAGES / "index.html")
@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def admin_page(): return FileResponse(PAGES / "admin.html")
@app.get("/{page}.html", include_in_schema=False)
def page(page: str):
    target = PAGES / f"{page}.html"
    if not target.is_file(): raise HTTPException(404, "Страница не найдена")
    return FileResponse(target)
app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "4173")), reload=False)
