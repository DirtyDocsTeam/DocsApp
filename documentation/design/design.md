# Дизайн и проектирование

Раздел описывает архитектуру DocsApp. **Источник правды по архитектуре — C4-диаграмма контекста
([`context.drawio`](context.drawio)) в её текущем виде.** Остальные артефакты раздела — ERD и
`db.sql` — сверяются с ней; всё, что расходится с C4, перечислено
в разделе [«Соответствие артефактов C4»](#соответствие-артефактов-c4) и считается отклонением,
которое нужно устранить или явно согласовать.

Продуктовый baseline (возможности, ограничения, требования безопасности и хранения) — в
[`.agents/PROJECT.md`](https://github.com/DirtyDocsTeam/DocsApp/blob/main/.agents/PROJECT.md);
он задаёт требования, но не переопределяет архитектуру из C4.

## Что в разделе

| Файл | Что это |
|---|---|
| `design.md` | эта страница: расшифровка C4, отклонения артефактов от неё, модель данных и открытые вопросы |
| `context.drawio` | C4-диаграмма контекста — **источник правды** по архитектуре (редактируется в diagrams.net / draw.io) |
| `context.jpg` | экспорт той же диаграммы для просмотра |
| `schema.svg`, `schema.png` | ERD: 12 таблиц PostgreSQL |
| `db.sql` | черновик DDL под ERD — проектный референс, **не** миграция (см. [дефекты черновика](#дефекты-черновика-dbsql)) |

## Контекст системы (C4) — источник правды

![Схема контекста C4 в формате draw.io](context.drawio)

![Диаграмма контекста](context.jpg)

Ниже — расшифровка диаграммы. Эти данные (стек контейнеров, протоколы, границы) считаются
действующими; если другой документ или артефакт говорит иначе, прав C4, а расхождение фиксируется
в разделе [«Соответствие артефактов C4»](#соответствие-артефактов-c4).

**Участники:** «Пользователь» (автор документа) и внешние системы — **External IDP** (GitHub/Google)
и **External LLM** (DeepSeek, используется только опциональным воркером генерации темы).

**Клиенты:** WEB Client (JS/React) и API Client (интеграция вида Obsidian). Оба входят через **Ingress**
(HAProxy) по REST или GraphQL.

**Контейнеры внутри границы системы `DirtyDocs`:**

| Контейнер | Технология | Назначение по диаграмме |
|---|---|---|
| Ingress | HAProxy | единая точка входа, маршрутизация REST/GraphQL, внешний путь к статике и медиа |
| IDProvider | Keycloak | идентификация пользователей, федерация с внешними IDP |
| Main API Plane | Quarkus | основное API приложения: приём и оркестрация задач |
| S3 Gateway Plane | Go | контролируемый прямой доступ клиентов к объектному хранилищу |
| Main Database | PostgreSQL | пользователи, стили, задачи, результаты, аудит |
| Object storage | SeaweedFS | пользовательские медиа, сгенерированные артефакты, статика сайта |
| Worker Pool `[Deployments]` | C#/C++, Python | `WorkerC-N` конвертация, `WorkerV-N` валидация, `WorkerT-N` шаблонизация, `WorkerG-N` генерация темы |

**Связи и протоколы:**

- WEB Client и API Client → Ingress: `REST/GQL`.
- Ingress → Main API Plane: `GQL [Main work]`; Ingress → IDProvider: `REST [OIDC]`;
  Ingress → S3 Gateway Plane: `S3 (Ext path) [Web static, Media artifacts]`.
- Main API Plane → IDProvider: `REST [Token validate]`; → Main Database: `SQLConn [App data, Job data]`;
  → S3 Gateway Plane: `gRPC [ID → S3://path, Token validate]`.
- IDProvider → External IDP: федерация; → Main Database: `SQLConn [ID data]`.
- S3 Gateway Plane → Object storage: `S3 (Int path)`.
- Main API Plane → Worker Pool: `gRPC [Job assign]`; Worker Pool → Main API Plane: `gRPC [Announce]`.
- Worker Pool → Object storage: `S3 [Media artifacts]`; `WorkerG-N` → External LLM.

Ключевое следствие для безопасности: клиент не получает доступ к бакету — только путь или подписанную
ссылку, выданную после проверки токена (см. «Открытые вопросы», п. 3).

## Соответствие артефактов C4

C4-диаграмма — источник правды; ниже — где остальные артефакты говорят иначе и что с этим делать.

| Артефакт | Что говорит | Расхождение с C4 | Что делать |
|---|---|---|---|
| `.agents/PROJECT.md`, `.agents/code-style/csharp.md` | Main API Plane и воркеры конвертации/валидации — C#/.NET | В C4 Main API Plane — Quarkus (JVM), воркеры `C#/C++` | привести baseline и гайды к C4 либо согласовать замену контейнера в C4 |
| ERD + `db.sql` (`users.oidc_token`) | токен OIDC хранится в основной БД | В C4 идентификация — Keycloak (`IDProvider`) с собственной БД, API лишь валидирует токен | убрать хранение OIDC-токена из `users`, оставить связь с субъектом Keycloak |
| ERD + `db.sql` (`api_tokens`) | собственные API-токены в основной БД | C4 не показывает отдельного хранилища токенов; для API-клиентов вход идёт через Ingress → Keycloak | определить, кто выпускает токены для API-клиентов (Keycloak или приложение) |
| ERD + `db.sql` (`media.storage_path`, `public_path`) | строковые пути в БД | В C4 доступ к объектам — через S3 Gateway Plane: внешний путь для статики и медиа, gRPC `[ID → S3://path, Token validate]` | хранить в БД ключи/идентификаторы объектов, а не готовые URL; выдача — через S3 Gateway |
| `job_request` | тип задачи `templating`/`conversion`/`validation`, без указания воркера | В C4 четыре независимых деплоймента `WorkerC/V/T/G`, назначение — `gRPC [Job assign]` | добавить признак назначенного воркера/пула и статуса доставки |
| `.agents/PROJECT.md` | доставка задач через RabbitMQ, прогресс — SSE/WebSocket, ссылки выдаёт API | В C4 нет брокера и канала нотификаций: отдача задач — `gRPC [Job assign]`, отчёт — `gRPC [Announce]`, ссылки — через S3 Gateway | либо добавить очередь и нотификации в C4, либо убрать их из baseline |
| `.agents/PROJECT.md` | публичный REST API с OpenAPI-контрактом | В C4 основной канал — `GQL [Main work]` | зафиксировать единый стиль API (или явно разделить поверхности: GQL для SPA, REST для внешних клиентов) |

## Модель данных

![ERD](schema.svg)

12 таблиц, четыре смысловые группы:

| Группа | Таблицы | Назначение |
|---|---|---|
| Идентификация и доступ | `users`, `api_tokens` | пользователи (`system_roles`, в т.ч. `admin`), их API-токены с `access`-политикой |
| Стили и темы | `themes`, `styles`, `theme_collections`, `theme_collection_themes`, `user_theme_collections` | тема → стили (`transform` / `render` / `validation`), коллекции тем, роли `owner`/`editor`/`viewer` |
| Задачи | `job_request`, `job_result`, `job_events`, `job_media` | запрос на `templating`/`conversion`/`validation` (`parent_request_id` — цепочка связанных запросов), результат, аудит-события, привязка вложений |
| Медиа | `media` | объекты в хранилище: `mime_type`, `storage_path`, `public_path`, `file_hash`, `is_non_cacheable`, `is_fast_deletable` |

ERD и `db.sql` сверены по колонкам всех 12 таблиц и совпадают; расхождения между ними больше нет.

Инварианты, заложенные в схему:

- **Изоляция арендаторов** — через `user_id` в `job_request`, `job_events`, `api_tokens` и роль в
  `user_theme_collections`; публичность темы/коллекции — флагом `is_public`.
- **Аудит** — `job_events.action` (`create_job`, `job_completed`, `job_failed`, `issue_download_url`)
  плюс произвольные `data`.
- **Дедупликация медиа** — по `file_hash`; `is_non_cacheable` выводит объект из кеша, `public_path`
  отделяет публичную статику от приватных артефактов.
- **`updated_at`** поддерживается триггером `set_updated_at()` на `users`, `theme_collections`,
  `themes`, `media` (в `job_request`, `job_result`, `api_tokens` таких колонок нет вовсе).

### Дефекты черновика `db.sql`

DDL в текущем виде не выполнится, а часть требований baseline им не выражается:

- **`CHECK (jsonb_typeof(preferences) = 'object')`** повторён 6 раз, но колонки `preferences` нет ни в одной
  таблице: проверка должна ссылаться на саму колонку (`access`, `parameters`, `data`). Сейчас это ошибка
  создания таблицы.
- **Пропущена запятая перед `PRIMARY KEY`** в `user_theme_collections`, `theme_collection_themes`,
  `job_media` — синтаксическая ошибка в составных первичных ключах.
- **`api_tokens.expired_at timestamptz NOT NULL DEFAULT now()`** — токен создаётся уже истёкшим;
  нужен `now() + interval` или `NULL` для бессрочных.
- **Статусы и типы — `varchar` с пояснением в комментарии** (в комментарии к статусу задачи опечатка
  `validationg`), без `CHECK`/`ENUM`: значения не защищены от опечаток.
- **Нет уникальности и индексов**: `users.email`, `api_tokens.token` не `UNIQUE`; нет индексов под
  типовые выборки (`job_request` по `user_id` + `status`, `media` по `file_hash`).
- **Нет временных меток у задач**: у `job_request` нет `created_at`/`updated_at` — не выстроить очередь
  и не посчитать SLA/MTTR.
- **Не выражено хранение результатов и отчётов**: нет `expires_at`/`deleted_at`, поэтому retention
  (результаты — 3 ч, вложения — 7 дней) и очистка не реализуемы из схемы; нет полей под
  `error_code`, `report_key`, `warnings[]`: без них не выразить терминальные статусы
  `FAILED`/`VALIDATION_FAILED` и отчёт о замечаниях.
- **Нет отзыва токенов**: у `api_tokens` нет `revoked_at`/`last_used_at`, хотя baseline требует отзыв
  токенов и лимит 100 запросов в минуту.
- **`job_request.parent_request_id bigint NOT NULL REFERENCES job_request(id)`** — самоссылка, объявленная
  `NOT NULL`: корневой запрос вставить нельзя, цепочка не может начаться. Для корневых нужен `NULL`.
- **`input_type`/`output_type varchar(4)`** — впритык: `docx` укладывается ровно, `markdown`/`docx+mermaid`
  уже нет; ограничения значений нет, а формат вывода — параметр запроса.
- **`users.oidc_token`**: по C4 идентификацию выполняет Keycloak, поэтому хранить сам OIDC-токен в основной
  БД не требуется, а это секрет; назначение `users.tokens` и `last_token_change` не задокументировано
  (квота? версия токенов?).
- **Удаление стиля**: `job_request.theme_id` ссылается на `themes` без `ON DELETE`, а baseline требует,
  чтобы удаление стиля не меняло завершённые задачи — нужен либо `ON DELETE SET NULL` со снапшотом
  параметров в `job_request.parameters`, либо запрет удаления используемой темы.

## Открытые вопросы

Отклонения от C4 из таблицы выше закрываются приведением артефактов к диаграмме; здесь — то, что
диаграмма не решает и что нужно решить отдельно.

1. **Публичный API-контракт.** C4 фиксирует `GQL [Main work]` как основной канал, а baseline требует
   публичный REST API с OpenAPI/Swagger. Нужно либо разделить поверхности (GQL для SPA, REST для внешних
   клиентов), либо согласовать отказ от REST в C4.
2. **Канал прогресса.** В C4 нет нотификаций, baseline опирается на SSE/WebSocket. Нужно решить,
   живёт ли прогресс в API (SSE/WS) и добавлять ли его в C4, или клиент остаётся на polling.
3. **Хранилище и выдача ссылок.** C4 отдаёт доступ через S3 Gateway Plane; в схеме остаются строковые
   пути `storage_path`/`public_path`. Определить ключи объектов, TTL подписанных ссылок и область их
   действия (job + tenant).
4. **Внешняя LLM.** Вызовы `WorkerG-N` → DeepSeek требуют согласия, минимизации данных, редакции
   и утверждённого правового основания; по умолчанию документы туда не отправляются.

## Как обновлять раздел

- Архитектура меняется в C4: правится `context.drawio`, затем обновляется экспорт `context.jpg`. После
  этого проверяется таблица «Соответствие артефактов C4» — она должна оставаться актуальной.
- После правки `db.sql` синхронизировать `schema.svg`/`schema.png`; когда схема стабилизируется,
  перейти на миграции — baseline прямо запрещает считать текущий черновик migration-ready.
- Коммит в `documentation/**` в ветке `main` пересобирает вики автоматически (workflow `docs → wiki`).
