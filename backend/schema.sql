-- Схема SQLite создаётся автоматически при старте backend/server.py.
-- Этот файл содержит её явное описание для проверки задания.
PRAGMA foreign_keys = ON;
CREATE TABLE users (login TEXT PRIMARY KEY, password TEXT NOT NULL, name TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0);
CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL, barcode TEXT NOT NULL DEFAULT '', ingredients TEXT NOT NULL DEFAULT '', allergens TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL DEFAULT 0);
CREATE TABLE profiles (login TEXT PRIMARY KEY REFERENCES users(login) ON DELETE CASCADE, restrictions TEXT NOT NULL DEFAULT '[]');
CREATE TABLE checks (id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT NOT NULL REFERENCES users(login), product_id INTEGER REFERENCES products(id) ON DELETE SET NULL, product_name TEXT NOT NULL, barcode TEXT NOT NULL DEFAULT '', checked_at TEXT NOT NULL, result TEXT NOT NULL, reason TEXT, matches TEXT NOT NULL DEFAULT '[]');
CREATE TABLE check_matches (check_id INTEGER NOT NULL REFERENCES checks(id) ON DELETE CASCADE, restriction TEXT NOT NULL, PRIMARY KEY(check_id, restriction));
CREATE TABLE stories (id TEXT PRIMARY KEY, title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '', image TEXT NOT NULL, href TEXT NOT NULL DEFAULT 'help.html');
CREATE INDEX idx_products_barcode ON products(barcode);
CREATE INDEX idx_checks_login_date ON checks(login, checked_at);
CREATE INDEX idx_check_matches_restriction ON check_matches(restriction);
