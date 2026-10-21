-- Схема SQLite проекта «Я Вижу!».
-- backend/server.py создаёт её сам при первом запуске (init_db) и дополняет старые базы через ALTER TABLE.
-- Файл повторяет итоговую схему, чтобы её можно было прочитать или создать базу вручную:
--   sqlite3 data/isee.sqlite3 < backend/schema.sql
PRAGMA foreign_keys = ON;

-- Пользователи. login — первичный ключ; у зарегистрированных по телефону он вида «phone:79001234567».
CREATE TABLE users (login TEXT PRIMARY KEY, password TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', is_admin INTEGER NOT NULL DEFAULT 0);

-- Сессии входа: хранится только SHA-256 токена. Удаляются вместе с пользователем.
CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, login TEXT NOT NULL REFERENCES users(login) ON DELETE CASCADE, expires_at INTEGER NOT NULL);

-- Профиль: список «Что мне нельзя» (JSON). Один к одному с users.
CREATE TABLE profiles (login TEXT PRIMARY KEY REFERENCES users(login) ON DELETE CASCADE, restrictions TEXT NOT NULL DEFAULT '[]');

-- Каталог «Товары для вас».
CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL, barcode TEXT NOT NULL DEFAULT '', ingredients TEXT NOT NULL DEFAULT '', allergens TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL DEFAULT 0);

-- Проверки товаров: кто проверил (users) и что (products). product_name — копия на случай удаления товара.
CREATE TABLE checks (id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT NOT NULL REFERENCES users(login), product_id INTEGER REFERENCES products(id) ON DELETE SET NULL, product_name TEXT NOT NULL, barcode TEXT NOT NULL DEFAULT '', checked_at TEXT NOT NULL, result TEXT NOT NULL, reason TEXT, matches TEXT NOT NULL DEFAULT '[]');

-- Найденные в проверке совпадения с ограничениями: один ко многим с checks.
-- Проверка и её совпадения пишутся одной транзакцией (POST /api/checks).
CREATE TABLE check_matches (check_id INTEGER NOT NULL REFERENCES checks(id) ON DELETE CASCADE, restriction TEXT NOT NULL, PRIMARY KEY(check_id, restriction));

-- Рецепты. ingredients и steps — JSON-массивы строк.
CREATE TABLE recipes (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', image TEXT NOT NULL, ingredients TEXT NOT NULL DEFAULT '[]', steps TEXT NOT NULL DEFAULT '[]', sponsored_product TEXT NOT NULL DEFAULT '', sponsored_label TEXT NOT NULL DEFAULT '');

-- Истории на главной: статья, рецепт (recipe_id → recipes) или инструкция (kind).
CREATE TABLE stories (id TEXT PRIMARY KEY, title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '', image TEXT NOT NULL, href TEXT NOT NULL DEFAULT 'help.html', recipe_id TEXT REFERENCES recipes(id) ON DELETE SET NULL, kind TEXT NOT NULL DEFAULT 'article', body TEXT NOT NULL DEFAULT '');

-- Кэш ответов нейросети и поиска состава (чтобы не тратить лимиты повторно).
CREATE TABLE ai_cache (cache_key TEXT PRIMARY KEY, response TEXT NOT NULL, expires_at INTEGER NOT NULL);

-- Индексы под частые запросы.
CREATE INDEX idx_sessions_login ON sessions(login);                         -- сессии пользователя
CREATE INDEX idx_products_barcode ON products(barcode);                     -- поиск товара по штрихкоду
CREATE INDEX idx_checks_login_date ON checks(login, checked_at);            -- история проверок пользователя по дате
CREATE INDEX idx_check_matches_restriction ON check_matches(restriction);   -- статистика по ограничениям
CREATE UNIQUE INDEX idx_users_phone ON users(phone) WHERE phone <> '';      -- один профиль на номер телефона
