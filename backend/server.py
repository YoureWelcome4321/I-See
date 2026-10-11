#!/usr/bin/env python3
"""FastAPI backend for the I-See project.

Run with: uvicorn backend.server:app --host 127.0.0.1 --port 4173 --reload
Swagger UI: /docs
"""
import os, re, secrets, threading, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

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

users = {"user": {"password": "qwerty", "name": "Пользователь"}, "admin": {"password": "12345", "name": "Администратор", "is_admin": True}}
tokens, products, checks = {}, [
    {"id": 1, "name": "Йогурт клубничный", "category": "Молочные продукты", "barcode": "4601234567890", "ingredients": "молоко, клубника, сахар", "allergens": "молоко", "price": 89},
    {"id": 2, "name": "Хлеб пшеничный", "category": "Выпечка", "barcode": "4601234567891", "ingredients": "пшеничная мука, вода, дрожжи", "allergens": "пшеница, глютен", "price": 65},
    {"id": 3, "name": "Шоколад с орехами", "category": "Сладости", "barcode": "4601234567892", "ingredients": "какао, сахар, фундук, молоко", "allergens": "фундук, орехи, молоко", "price": 149},
], []
profiles = {key: [] for key in users}
stories = [{"id": f"story-{i:02d}", "title": title, "subtitle": subtitle, "image": f"story-{i:02d}.jpg", "href": href} for i, (title, subtitle, href) in enumerate((("Новый образ", "Детали и настроение", "help.html"), ("Город не спит", "Вечерние огни", "help.html"), ("Тёплый вечер", "Моменты на память", "medical-card.html"), ("Wanna play?", "Новая игра", "feedback.html"), ("Особенный день", "Важные события", "help.html"), ("Вечер дома", "Время для себя", "help.html"), ("Другой взгляд", "Игра света и тени", "help.html")), 1)]
lock = threading.RLock()

SWAGGER_TAGS = [
    {"name": "Система", "description": "Проверка доступности и состояния сервера."},
    {"name": "Авторизация", "description": "Вход пользователей и выдача bearer-токенов."},
    {"name": "Каталог товаров", "description": "Получение и управление товарами каталога."},
    {"name": "Профиль и проверки", "description": "Ограничения питания и личная история проверок."},
    {"name": "Истории", "description": "Истории, отображаемые на главной странице."},
    {"name": "Администрирование", "description": "Защищённые операции администратора."},
    {"name": "Магазины", "description": "Поиск ближайших магазинов через OpenStreetMap."},
    {"name": "Open Food Facts", "description": "Получение данных о продукте по штрихкоду."},
]
app = FastAPI(title="Я Вижу! API", description="API сервиса проверки состава продуктов", version="1.0.0", openapi_tags=SWAGGER_TAGS)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class LoginData(BaseModel): login: str; password: str
class ProductData(BaseModel):
    name: str = Field(min_length=1, max_length=120); category: str = "Продукты"; barcode: str = ""; ingredients: str = ""; allergens: str = ""; price: int = Field(default=0, ge=0, le=10000000)
class ProfileData(BaseModel): restrictions: list[dict] = Field(default_factory=list, max_length=100)
class CheckData(BaseModel): product_id: int | None = None; product: dict | None = None
class StoryData(BaseModel): id: str = ""; title: str = Field(min_length=1, max_length=60); subtitle: str = ""; image: str; href: str = "help.html"

def user_from_token(authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "): return None
    return tokens.get(authorization.split(" ", 1)[1].strip())
def require_user(authorization):
    user = user_from_token(authorization)
    if not user: raise HTTPException(401, "Войдите в профиль для этого действия")
    return user
def require_admin(authorization):
    user = require_user(authorization)
    if not users.get(user, {}).get("is_admin"): raise HTTPException(403, "Это действие доступно только администратору")
    return user
def clean_product(data):
    return {"name": data.name.strip(), "category": data.category.strip()[:80], "barcode": data.barcode.strip()[:32], "ingredients": data.ingredients.strip()[:2000], "allergens": data.allergens.strip()[:500], "price": data.price}

@app.get("/api/health", tags=["Система"], summary="Проверить работу сервера", description="Возвращает простой признак доступности backend-сервера. Авторизация не требуется.")
def health(): return {"ok": True}
@app.post("/api/login", tags=["Авторизация"], summary="Войти в аккаунт", description="Проверяет логин и пароль, после чего выдаёт bearer-токен для защищённых запросов.")
def login(data: LoginData):
    account = users.get(data.login.strip())
    if not account or not secrets.compare_digest(data.password, account["password"]): raise HTTPException(401, "Неверный логин или пароль")
    token = secrets.token_urlsafe(24); tokens[token] = data.login.strip()
    return {"token": token, "user": {"login": data.login.strip(), "name": account["name"], "is_admin": bool(account.get("is_admin"))}}

@app.get("/api/products", tags=["Каталог товаров"], summary="Получить каталог товаров", description="Возвращает все товары, доступные на странице каталога. Авторизация не требуется.")
def get_products(): return products
@app.post("/api/products", status_code=201, tags=["Каталог товаров"], summary="Добавить товар в каталог", description="Создаёт новый товар в каталоге. Доступно только администратору с bearer-токеном.")
def add_product(data: ProductData, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    item = {"id": max((p["id"] for p in products), default=0) + 1, **clean_product(data)}; products.append(item); return item
@app.get("/api/products/{item_id}", tags=["Каталог товаров"], summary="Получить один товар", description="Возвращает подробную информацию о товаре по его числовому идентификатору.")
def get_product(item_id: int):
    item = next((p for p in products if p["id"] == item_id), None)
    if not item: raise HTTPException(404, "Товар не найден")
    return item
@app.put("/api/products/{item_id}", tags=["Каталог товаров"], summary="Изменить товар", description="Полностью обновляет данные товара. Доступно только администратору с bearer-токеном.")
def update_product(item_id: int, data: ProductData, authorization: str | None = Header(default=None)):
    require_admin(authorization); item = next((p for p in products if p["id"] == item_id), None)
    if not item: raise HTTPException(404, "Товар не найден")
    item.update(clean_product(data)); return item
@app.delete("/api/products/{item_id}", tags=["Каталог товаров"], summary="Удалить товар", description="Удаляет товар из каталога по идентификатору. Доступно только администратору с bearer-токеном.")
def delete_product(item_id: int, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    for i, item in enumerate(products):
        if item["id"] == item_id: return {"deleted": products.pop(i)}
    raise HTTPException(404, "Товар не найден")

@app.get("/api/profile", tags=["Профиль и проверки"], summary="Получить ограничения профиля", description="Возвращает сохранённые аллергии и продукты, которых пользователь избегает. Требуется авторизация.")
def get_profile(authorization: str | None = Header(default=None)):
    user = require_user(authorization); return {"restrictions": profiles.get(user, [])}
@app.post("/api/profile", tags=["Профиль и проверки"], summary="Сохранить ограничения профиля", description="Сохраняет список аллергий и ограничений питания текущего пользователя. Требуется авторизация.")
def save_profile(data: ProfileData, authorization: str | None = Header(default=None)):
    user = require_user(authorization); clean = []
    for item in data.restrictions:
        if isinstance(item, dict) and item.get("type") in ("allergy", "avoid") and str(item.get("name", "")).strip(): clean.append({"type": item["type"], "name": str(item["name"]).strip()[:80]})
    profiles[user] = clean; return {"restrictions": clean}
@app.get("/api/checks", tags=["Профиль и проверки"], summary="Получить историю проверок", description="Возвращает только проверки текущего авторизованного пользователя, отсортированные в порядке сохранения.")
def get_checks(authorization: str | None = Header(default=None)):
    user = require_user(authorization); return [x for x in checks if x["user"] == user]
@app.post("/api/checks", status_code=201, tags=["Профиль и проверки"], summary="Проверить и сохранить товар", description="Сравнивает состав товара с ограничениями профиля, рассчитывает результат проверки и сохраняет запись в личную историю пользователя.")
def save_check(data: CheckData, authorization: str | None = Header(default=None)):
    user = require_user(authorization); product = next((p for p in products if p["id"] == data.product_id), None)
    if not product and data.product:
        product = {"id": None, "name": str(data.product.get("name", "")).strip(), "barcode": str(data.product.get("barcode", "")), "ingredients": str(data.product.get("ingredients", "")), "allergens": str(data.product.get("allergens", ""))}
    if not product or not product.get("name"): raise HTTPException(404, "Товар не найден")
    restrictions = [x["name"].casefold() for x in profiles.get(user, [])]; source = f"{product.get('allergens', '')} {product.get('ingredients', '')}".casefold(); matches = [x for x in restrictions if x in source]
    result = "warning" if matches else "clear" if restrictions and source.strip() else "unknown"; reason = None if result != "unknown" else "no_restrictions" if not restrictions else "product_data_missing"
    record = {"id": len(checks) + 1, "user": user, "product_id": product.get("id"), "product_name": product["name"], "barcode": product.get("barcode", ""), "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "result": result, "reason": reason, "matches": matches}; checks.append(record); return record

@app.get("/api/stories", tags=["Истории"], summary="Получить истории для главной", description="Возвращает подписи, изображения и ссылки историй, которые отображаются в верхнем блоке главной страницы.")
def get_stories(): return stories
@app.get("/api/admin/users", tags=["Администрирование"], summary="Посмотреть список пользователей", description="Возвращает имена, логины, роли и количество проверок пользователей. Доступно только администратору.")
def admin_users(authorization: str | None = Header(default=None)):
    require_admin(authorization); return [{"login": login, "name": account.get("name", login), "is_admin": bool(account.get("is_admin")), "checks_count": sum(x["user"] == login for x in checks)} for login, account in users.items()]
@app.get("/api/admin/checks", tags=["Администрирование"], summary="Посмотреть все проверки", description="Возвращает общую историю проверок всех пользователей для административного просмотра.")
def admin_checks(authorization: str | None = Header(default=None)):
    require_admin(authorization); return checks
@app.get("/api/admin/stories", tags=["Администрирование"], summary="Получить истории в админке", description="Возвращает полный список историй для редактирования в панели администратора.")
def admin_stories(authorization: str | None = Header(default=None)): require_admin(authorization); return stories
@app.post("/api/admin/stories", tags=["Администрирование"], summary="Создать или изменить историю", description="Создаёт новую историю или обновляет существующую, если передан её идентификатор. Доступно только администратору.")
def save_story(data: StoryData, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    if not re.fullmatch(r"story-\d{2}\.jpg", data.image) or not re.fullmatch(r"(?:[a-zA-Z0-9-]+\.html|/)", data.href): raise HTTPException(400, "Некорректные данные истории")
    if data.id:
        item = next((x for x in stories if x["id"] == data.id), None)
        if not item: raise HTTPException(404, "История не найдена")
        item.update(data.model_dump()); return item
    item = {"id": f"story-{secrets.token_hex(3)}", **data.model_dump(exclude={"id"})}; stories.append(item); return item
@app.delete("/api/admin/stories/{story_id}", tags=["Администрирование"], summary="Удалить историю", description="Удаляет историю главной страницы по идентификатору. Доступно только администратору.")
def delete_story(story_id: str, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    for i, item in enumerate(stories):
        if item["id"] == story_id: return {"deleted": stories.pop(i)}
    raise HTTPException(404, "История не найдена")

@app.get("/api/off/products/{barcode}", tags=["Open Food Facts"], summary="Найти продукт по штрихкоду", description="Запрашивает состав и сведения о продукте во внешнем сервисе Open Food Facts по штрихкоду.")
def off_product(barcode: str, fields: str = "product_name,product_name_ru,brands,quantity,ingredients_text,ingredients_text_ru,allergens,allergens_tags,additives_n,additives_tags,additives_original_tags,image_front_url,image_front_small_url"):
    try:
        req = Request(f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json?{urlencode({'fields': fields})}", headers={"User-Agent": "ISeeFoodAssistant/1.0"})
        with urlopen(req, timeout=12) as response: return __import__('json').loads(response.read().decode())
    except Exception as exc: raise HTTPException(502, f"Open Food Facts недоступен: {exc}")

@app.get("/api/stores", tags=["Магазины"], summary="Найти магазины рядом", description="Ищет продуктовые магазины в радиусе 2 километров от переданных координат через OpenStreetMap.")
def stores(lat: float = Query(...), lon: float = Query(...)):
    query = '[out:json][timeout:20];(nwr["shop"~"^(supermarket|convenience|greengrocer|bakery|department_store)$"]' + f'(around:{STORE_RADIUS_METERS},{lat},{lon}););out center tags;'
    for provider in STORE_PROVIDERS:
        try:
            req = Request(provider, data=urlencode({"data": query}).encode(), headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ISeeFoodAssistant/1.0"}, method="POST")
            with urlopen(req, timeout=13) as response: return __import__('json').loads(response.read().decode())
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
