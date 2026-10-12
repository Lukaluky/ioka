# Travel Booking API

Сервис бронирования авиабилетов для турагентов. Полный цикл: логин агента → поиск IATA-кодов →
асинхронный поиск офферов с поллингом → детали оффера → бронь → выписка со списанием баланса →
PDF билета.

Тестовое задание на позицию middle backend-разработчика. Акцент — на корректности (деньги,
идемпотентность, конкурентность), чистой архитектуре и тестах, а не на количестве фич.

## Стек

Python 3.11, FastAPI, SQLAlchemy 2.x (async) + asyncpg, Alembic, PostgreSQL 16, Redis 7,
RabbitMQ 3 (aio-pika), PyJWT, bcrypt, reportlab, pytest, Docker Compose.

## Архитектура

Clean / Hexagonal Architecture. Правило зависимостей строгое и одностороннее:

```
app/
  domain/          сущности и value objects (Agent, Order, Offer, Money, Transaction...),
                    доменные ошибки, state machine заказа. Ничего не импортирует из проекта
                    и никаких фреймворков.
  application/      use case-ы (LoginAgent, StartSearch, CreateOrder, IssueOrder, GetTicket...)
                    и порты — Protocol-интерфейсы (AgentRepository, AirProvider, UnitOfWork...).
                    Импортирует только domain и свои порты.
  infrastructure/   адаптеры: SQLAlchemy-репозитории, Redis, RabbitMQ, MockAirProvider,
                    security (bcrypt/JWT), генерация PDF. Реализует порты из application.
  api/              FastAPI-роутеры, Pydantic-схемы, DI (deps.py), маппинг DomainError → HTTP.
  worker/           консьюмеры RabbitMQ (поиск, генерация билета) и outbox relay.
  cli/              create_agent, load_airports.
```

```
api/worker ──> application (use cases, порты)  <── infrastructure (реализации портов)
                       │
                       ▼
                    domain
```

`api` и `worker` — composition root: собирают use case-ы из конкретных адаптеров и вызывают их.
ORM-модели никогда не покидают `infrastructure` — наружу всегда отдаются доменные объекты.

## Как запустить

```powershell
cp .env.example .env          # заполнить секреты (пароли БД/RabbitMQ, JWT_SECRET)
docker compose up --build -d
```

Поднимутся `postgres`, `redis`, `rabbitmq`, разовый `migrate` (накатывает Alembic-миграции),
`api` (http://localhost:8000) и `worker`. Swagger: http://localhost:8000/docs.

### Создать агента и загрузить аэропорты

```powershell
docker compose run --rm api python -m app.cli.create_agent --login agent1 --name "Test Agent" --balance 1000000 --currency USD
docker compose run --rm api python -m app.cli.load_airports
```

`create_agent` спрашивает пароль интерактивно (в аргументах его нет). `load_airports` тянет
`airports.csv` из открытого справочника OurAirports и идемпотентно заполняет таблицу `locations`
(upsert по `iata_code`) — повторный запуск безопасен.

### Тесты и линт

```powershell
docker compose run --rm api pytest
docker compose run --rm api ruff check .
docker compose run --rm api mypy app
```

## Пример флоу (curl)

```bash
TOKEN=$(curl -s -X POST localhost:8000/travel/auth/agent/login \
  -H "Content-Type: application/json" \
  -d '{"login":"agent1","password":"<пароль из create_agent>"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Поиск локаций
curl -s "localhost:8000/travel/avia/locations?query=alm" -H "Authorization: Bearer $TOKEN"

# Старт поиска офферов (202 + search_id)
SEARCH_ID=$(curl -s -X POST localhost:8000/travel/avia/offers \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"origin":"ALA","destination":"IST","departure_date":"2026-12-20","passengers":{"adults":1},"cabin":"economy"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['search_id'])")

# Поллинг (пара секунд, пока воркер не вызовет провайдер)
curl -s "localhost:8000/travel/avia/offers/search/$SEARCH_ID" -H "Authorization: Bearer $TOKEN"

# Детали оффера (OFFER_ID и STANDARD — из предыдущего ответа)
curl -s "localhost:8000/travel/avia/offers/$OFFER_ID" -H "Authorization: Bearer $TOKEN"

# Бронь — Idempotency-Key обязателен
ORDER_ID=$(curl -s -X POST localhost:8000/travel/avia/orders \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(python -c 'import uuid;print(uuid.uuid4())')" \
  -d '{"offer_id":"'"$OFFER_ID"'","fare_family":"STANDARD","passengers":[{"type":"ADT","first_name":"IVAN","last_name":"IVANOV","birth_date":"1995-03-10","gender":"M","citizenship":"KZ","document_number":"N12345678","document_expiry":"2030-01-01"}],"contact":{"email":"agent@example.com","phone":"+77001234567"}}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['id'])")

# Выписка — списание баланса + вызов провайдера
curl -s -X POST "localhost:8000/travel/avia/orders/$ORDER_ID/issue" -H "Authorization: Bearer $TOKEN"

# PDF билета (появляется через пару секунд — работает outbox relay + генерация)
curl -s "localhost:8000/travel/avia/orders/$ORDER_ID/ticket" -H "Authorization: Bearer $TOKEN" -o ticket.pdf
```

## Ключевые решения

- **Идемпотентность брони.** `Idempotency-Key` + sha256 от канонического JSON тела хранятся в
  `idempotency_keys` с `unique(agent_id, key)`. Повтор с тем же ключом/телом возвращает тот же
  заказ (200); с другим телом — 409. При гонке двух параллельных запросов с одним ключом второй
  инсерт падает на unique-констрейнте — use case откатывает транзакцию и перечитывает уже
  созданный заказ победителя. Гарантия на уровне БД, а не только в коде.
- **Леджер, а не просто баланс.** Каждое движение денег — отдельная строка в `transactions`
  (`DEBIT`/`REFUND`/`TOPUP`) с `balance_after`. `unique(order_id, kind)` делает двойное списание
  или двойной возврат по одному заказу физически невозможным на уровне БД, даже если бы в коде
  была ошибка.
- **Outbox, а не публикация из бизнес-транзакции.** Событие `ticket.generate` пишется в таблицу
  `outbox` в той же транзакции, что и перевод заказа в `ISSUED` — значит оно либо случится вместе
  с бизнес-изменением, либо не случится вовсе (никогда не бывает «деньги списали, а событие
  потерялось»). Отдельный relay в воркере раз в секунду забирает неопубликованные строки
  (`FOR UPDATE SKIP LOCKED` — безопасно при нескольких инстансах воркера) и публикует в RabbitMQ.
- **Выписка в две транзакции (SPEC §10).** Транзакция 1: `SELECT ... FOR UPDATE` заказа и агента,
  списание, `DEBIT`, перевод в `ISSUING`, commit — лочит строки на минимальное время. Вызов
  внешнего провайдера происходит **вне** транзакции БД (сетевой вызов может занять секунды,
  держать лок всё это время нельзя). Транзакция 2: при успехе — `ISSUED` + номера билетов +
  событие в outbox; при ошибке/таймауте — `REFUND` и `ISSUE_FAILED`. Конкурентные `issue` одного
  заказа сериализуются через блокировку строки заказа: второй запрос видит уже `ISSUING` и
  получает 409, а не повторное списание.
- **Mock-провайдер как честная замена реального.** `AirProvider` — Protocol-порт с методами
  `search/get_offer/issue`; `MockAirProvider` — единственная реализация, но архитектура позволяет
  добавить Amadeus/Duffel отдельным адаптером без изменения use case-ов. Данные детерминированы
  по `(origin, destination, departure_date)` — одинаковый поиск даёт одинаковый набор рейсов/цен,
  что удобно для тестов и отладки. Декоратор `AuditingAirProvider` пишет каждый вызов (успех,
  ошибку, таймаут) в `provider_requests`, маскируя номера документов пассажиров.
