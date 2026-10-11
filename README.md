# Я Вижу!

Проект разделён на frontend и backend:

- `frontend/pages/` — HTML-страницы;
- `frontend/assets/css/` — стили;
- `frontend/assets/js/` — клиентская логика;
- `frontend/assets/images/` — изображения;
- `backend/server.py` — FastAPI-сервер, статические страницы и API-прокси.

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
- `POST /api/login` — вход и получение учебного bearer-токена;
- `GET/POST /api/profile` — ограничения питания авторизованного пользователя; (В работе)
- `GET/POST /api/checks` — личная история проверок. При сохранении сервер связывает проверку с товаром и сравнивает состав с ограничениями профиля; (В работе)
- `GET /api/stores?lat={latitude}&lon={longitude}` — продуктовые магазины в радиусе 2 км через Overpass/OpenStreetMap.

Учебные аккаунты: `user / qwerty` и `admin / 12345`. Панель управления доступна по адресу <http://127.0.0.1:4173/admin/>. В ней можно добавлять, редактировать и удалять товары, просматривать пользователей, а также добавлять, редактировать и удалять истории главной страницы (для историй выбираются уже загруженные в `frontend/assets/images/` изображения). Создание новых пользователей из админки недоступно. API дополнительно проверяет права на сервере. В обычном аккаунте откройте товар и сохраните проверку, затем посмотрите её в «Профиль → Мои проверки». Данные, токены и история хранятся только в памяти сервера и сбросятся при перезапуске. Авторизация и пароли демонстрационные — для реального сайта так хранить учётные записи нельзя.

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
