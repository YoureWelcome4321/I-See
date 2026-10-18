# Я Вижу!

Swagger со всеми маршрутами - /docs

Проект разделён на frontend и backend:

- `frontend/pages/` — HTML-страницы;
- `frontend/assets/css/` — стили;
- `frontend/assets/js/` — клиентская логика;
- `frontend/assets/images/` — изображения;
- `backend/server.py` — FastAPI-сервер, статические страницы и API.
- `backend/schema.sql` — схема SQLite;
- `backend/backup.py` — создание и восстановление резервной копии;
- `data/isee.sqlite3` — рабочая база (создаётся автоматически, не коммитится).

## Запуск

Требуется Python 3.10+ и зависимости из `requirements.txt`.

```bash
python3 -m pip install -r requirements.txt
python3 backend/server.py
```

Затем откройте <http://127.0.0.1:4173>. Другой порт можно задать переменной `PORT`, адрес привязки — `HOST`. Документация Swagger доступна по адресу <http://127.0.0.1:4173/docs>, альтернативная документация ReDoc — по адресу <http://127.0.0.1:4173/redoc>.

## API

- `GET /api/health` — состояние сервера;
- `GET /api/products` и `GET /api/products/{id}` — учебный каталог;
- `POST /api/products`, `PUT /api/products/{id}` и `DELETE /api/products/{id}` — управление каталогом (только администратор);
- `GET /api/stories` — истории для главной страницы;
- `GET /api/admin/users` и `GET /api/admin/checks` — служебный просмотр пользователей и проверок (только администратор);
- `GET /api/admin/users` — просмотр пользователей, а `GET /api/admin/stories`, `POST /api/admin/stories`, `DELETE /api/admin/stories/{id}` — администрирование историй (только администратор);
- `GET /api/off/products/{barcode}` — данные от Open Food Facts для штрихкода;
- `POST /api/ai/product-details` — поиск недостающих данных о составе через OpenRouter с веб-поиском; ответ содержит только подтверждённые значения в `fields`, а запрошенные, но не найденные после повторного поиска поля — в `missing`;
- `POST /api/login` — вход и получение учебного bearer-токена;
- `GET/POST /api/profile` — ограничения питания авторизованного пользователя; (В работе)
- `GET/POST /api/checks` — личная история проверок. При сохранении сервер связывает проверку с товаром и сравнивает состав с ограничениями профиля; (В работе)
- `GET /api/stores?lat={latitude}&lon={longitude}` — продуктовые магазины в радиусе 2 км через Overpass/OpenStreetMap.

Учебные аккаунты: `user / qwerty` и `admin / 12345`. Каталог, профили, проверки, пользователи и истории хранятся в SQLite и переживают перезапуск сервера. Проверка сохраняется транзакцией в `checks` и `check_matches`; история отдаётся через `LEFT JOIN` с товарами. Индексы созданы для штрихкода, истории пользователя и совпадений ограничений. Авторизация и пароли демонстрационные — для реального сайта так хранить учётные записи нельзя.

### База, JOIN, транзакции и backup

При первом запуске создаётся `data/isee.sqlite3`. Схема и внешние ключи описаны в `backend/schema.sql`. Для ручной проверки сохранения: войдите, сохраните профиль/проверку, перезапустите backend и повторите `GET /api/checks`.

```bash
# дамп базы
python3 backend/backup.py backup backup.sqlite3
# восстановление после удаления строк/файла
python3 backend/backup.py restore backup.sqlite3
```

Проверить индексы можно командой `sqlite3 data/isee.sqlite3 '.indexes'`, а план JOIN — `EXPLAIN QUERY PLAN SELECT c.*, p.name FROM checks c LEFT JOIN products p ON p.id=c.product_id;`.

Пример проверки через curl:

```bash
curl -X POST http://127.0.0.1:4173/api/login \
  -H 'Content-Type: application/json' \
  -d '{"login":"user","password":"qwerty"}'

# Подставьте token из ответа на вход:
curl -X POST http://127.0.0.1:4173/api/checks \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer token' \
  -d '{"product_id":1}'
curl http://127.0.0.1:4173/api/checks -H 'Authorization: Bearer token'
```

Backend раздаёт страницы и ресурсы с того же origin, поэтому браузеру не нужны CORS-запросы к API продуктов и магазинов. Карта и её тайлы Leaflet/OpenStreetMap по-прежнему загружаются из внешних источников. Для камеры браузеру нужен HTTPS: в production запускайте Python backend за HTTPS reverse proxy (например, Nginx).

### Поиск недостающего состава через ИИ

Для поиска по интернету создайте API-ключ в [OpenRouter](https://openrouter.ai/keys) и перед запуском backend задайте переменную `OPENROUTER_API_KEY`. В macOS/Linux в том же окне терминала:

```bash
export OPENROUTER_API_KEY="ваш_ключ_openrouter"
python3 backend/server.py
```

Ключ хранится только в окружении Python-сервера и не отправляется браузеру. Если Open Food Facts не содержит состава, аллергенов, добавок, пищевой ценности или сведений о товаре, карточка дополнительно запрашивает модель через OpenRouter с web-плагином. По умолчанию используется фиксированная `openai/gpt-4.1-mini` вместо `openrouter/free`, так как случайное переключение между бесплатными моделями давало нестабильные форматы и неполные карточки. Эта модель и веб-поиск могут быть платными; проверьте стоимость и лимиты в OpenRouter. Модель можно изменить через `OPENROUTER_MODEL`. Сервер проверяет фактические значения и один раз повторяет поиск только для незаполненных полей. `fields` содержит найденные сведения, `missing` — поля, которые не удалось извлечь. Запросы к ИИ кэшируются на час и ограничены 12 запросами в час с одного IP. ИИ-результат не подтверждает безопасность продукта — при аллергии всегда сверяйте упаковку.
