# Дизайн и проектирование

Раздел детализирует архитектуру DocsApp: контекст системы, сценарий конвертации и модель данных.
Продуктовый baseline (возможности, ограничения, требования безопасности и хранения) — в
[`.agents/PROJECT.md`](https://github.com/DirtyDocsTeam/DocsApp/blob/main/.agents/PROJECT.md);
здесь — диаграммы и схема БД, которые к нему прилагаются, и список расхождений, которые нужно закрыть до реализации.

## Что в разделе

| Файл | Что это |
|---|---|
| `design.md` | эта страница: обзор, расшифровка диаграмм, расхождения и открытые вопросы |
| `context.drawio` | C4-диаграмма контекста (источник, редактируется в diagrams.net / draw.io) |
| `context.jpg` | экспорт той же диаграммы для просмотра |
| `03-conversion-sequence.png` | UML-диаграмма последовательности: асинхронная конвертация от запроса до скачивания |
| `schema.svg`, `schema.png` | ERD: 12 таблиц PostgreSQL |
| `db.sql` | черновик DDL под ERD — проектный референс, **не** миграция (см. [дефекты черновика](#дефекты-черновика-dbsql)) |

## Контекст системы (C4)

![Схема контекста C4 в формате draw.io](context.drawio)

![Диаграмма контекста](context.jpg)

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
ссылку, выданную после проверки токена (см. «Открытые вопросы», п. 4).

## Сценарий конвертации

![Диаграмма последовательности конвертации](03-conversion-sequence.png)

Участники: `User`, `FE`, `API`, `S3`, `DB`, `MQ`, `Server`.

1. **Проверка входа.** Если превышен размер основного файла или суммарный размер вложений —
   `413 Payload Too Large`, задача не создаётся (лимиты baseline: 10 МБ на файл, 150 МБ на вложения).
2. **Постановка задачи.** `POST /jobs`: исходник и вложения сохраняются в S3 под `jobs/{job_id}/input/`,
   в БД создаётся `ConversionJob` (`status=QUEUED`, `style_id`, `output_format`, `expires_at`),
   пишется аудит-событие `create_job`, в очередь публикуется `ConversionJob(job_id)`, ответ — `202 Accepted`
   с `job_id` и `status_url`.
3. **Прогресс.** Клиент подписывается на WebSocket или опрашивает
   `GET /api/v1/conversions/{job_id}`; ответ содержит `status` и `progress` (polling остаётся
   совместимым путём).
4. **Обработка.** Воркер получает сообщение из очереди, ставит `PARSING` и `started_at`, скачивает исходник
   и вложения из S3, разбирает Markdown (AST, ссылки, картинки, таблицы, сноски), затем ставит `RENDERING`.
   Ошибка рендера Mermaid/PlantUML/LaTeX/блоков кода — отдельная ветка: лог ошибки, `FAILED`,
   `error_code=RENDER_ERROR`, клиенту доступен отчёт об ошибке.
5. **Сборка.** `BUILDING`: применяется выбранный стиль и собирается целевой формат — `output_format`
   ветвит сборку (для DOCX — OOXML, шрифты, отступы, автонумерация, таблицы, рисунки, ссылки;
   для PDF — страницы, колонтитулы, шрифты, оглавление; ODT — стили абзацев и нумерация).
6. **Валидация.** `VALIDATING`: валидатор проверяет оформление по стилю — максимальную глубину списков,
   пунктуацию, обязательные элементы, нумерацию, ссылки.
7. **Терминальные состояния.**
   - ошибок нет → результат и отчёт сохраняются в `jobs/{job_id}/output/`, `COMPLETED`,
     `expires_at = now + 3 ч`, метрики; клиент получает подписанные URL на результат и отчёт (TTL ≤ 3 ч),
     аудит-событие `issue_download_url`, скачивание идёт напрямую из хранилища;
   - есть замечания, результат пригоден → `COMPLETED_WITH_WARNINGS` и список `warnings[]`;
   - критические ошибки стиля → `VALIDATION_FAILED`, `error_code=STYLE_VALIDATION_ERROR`,
     выдаётся только отчёт с `issues[]`, итоговый файл не отдаётся (или помечается черновиком).

Инварианты сценария: повторная доставка сообщения не должна создавать дубликаты результата или событий;
подписанные ссылки выдаются только на валидный результат; любое действие с задачей проверяет владельца.

## Модель данных

![ERD](schema.svg)

12 таблиц, четыре смысловые группы:

| Группа | Таблицы | Назначение |
|---|---|---|
| Идентификация и доступ | `users`, `api_tokens` | пользователи (`system_roles`, в т.ч. `admin`), их API-токены с `access`-политикой |
| Стили и темы | `themes`, `styles`, `theme_collections`, `theme_collection_themes`, `user_theme_collections` | тема → стили (`transform` / `render`), коллекции тем, роли `owner`/`editor`/`viewer` |
| Задачи | `job_request`, `job_result`, `job_events`, `job_media` | запрос на `templating`/`conversion`, результат, аудит-события, привязка вложений |
| Медиа | `media` | объекты в хранилище: `mime_type`, `storage_path`, `public_path`, `file_hash` |

Инварианты, заложенные в схему:

- **Изоляция арендаторов** — через `user_id` в `job_request`, `job_events`, `api_tokens` и роль в
  `user_theme_collections`; публичность темы/коллекции — флагом `is_public`.
- **Аудит** — `job_events.action` (`create_job`, `job_completed`, `job_failed`, `issue_download_url`)
  плюс произвольные `data`.
- **Дедупликация медиа** — по `file_hash`; `is_non_cacheable` выводит объект из кеша, `public_path`
  отделяет публичную статику от приватных артефактов.
- **`updated_at`** поддерживается триггером `set_updated_at()` на `users`, `theme_collections`,
  `themes`, `media` (в `job_request`, `job_result`, `api_tokens` таких колонок нет вовсе).

### Расхождения ERD и `db.sql`

Диаграмма и DDL уже разошлись — при реализации нужно выбрать одну версию:

| Таблица | Только в ERD (`schema.svg`/`schema.png`) | Только в `db.sql` |
|---|---|---|
| `job_request` | `parent_request_id`, `processing_media_id`, `input_type`, `output_type` | `processing_file_path` |
| `job_result` | `result_media_id` | `storage_path` |
| `media` | `is_fast_deletable` | — |

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
  `error_code`, `report_key`, `warnings[]`, которые требует диаграмма последовательности.
- **Нет отзыва токенов**: у `api_tokens` нет `revoked_at`/`last_used_at`, хотя baseline требует отзыв
  токенов и лимит 100 запросов в минуту.
- **`users.oidc_token`**: при валидации токенов в Keycloak хранить сам токен в БД не требуется, а это
  секрет; назначение `users.tokens` и `last_token_change` не задокументировано (квота? версия токенов?).
- **Удаление стиля**: `job_request.theme_id` ссылается на `themes` без `ON DELETE`, а baseline требует,
  чтобы удаление стиля не меняло завершённые задачи — нужен либо `ON DELETE SET NULL` со снапшотом
  параметров в `job_request.parameters`, либо запрет удаления используемой темы.

## Открытые вопросы

1. **Стек Main API Plane.** На диаграмме контекста — Quarkus (JVM), в baseline и в
   `.agents/code-style/` — C#/.NET. Нужно зафиксировать один вариант до старта работ.
2. **Доставка задач воркерам.** На диаграмме последовательности есть `MQ` (durable-очередь), на диаграмме
   контекста — `gRPC [Job assign]` / `gRPC [Announce]`. Остаётся ли RabbitMQ очередью, а gRPC — каналом
   постановки/отчёта?
3. **Стиль API.** Контекст показывает `GQL [Main work]`, последовательность — REST `/api/v1/conversions/{job_id}`.
   Нужен ли GraphQL в дополнение к REST, и кто публикует OpenAPI-контракт?
4. **Модель доступа к S3.** Схема выдаёт «ID → S3://path» после валидации токена: нужны короткоживущие
   job/tenant-scoped ссылки или временные креды, но не проксирование бакета.
5. **Источник диаграммы последовательности.** В репозитории только PNG: исходник (Mermaid/PlantUML/draw.io)
   стоит завести, иначе правки диаграммы не воспроизводимы.
6. **Внешняя LLM.** Вызовы `WorkerG-N` → DeepSeek требуют согласия, минимизации данных, редакции
   и утверждённого правового основания; по умолчанию документы туда не отправляются.

## Как обновлять раздел

- Диаграммы в draw.io: правится `context.drawio`, затем обновляется экспорт `context.jpg`.
- `03-conversion-sequence.png`: обновлять вместе с исходником (см. п. 5 выше).
- После правки `db.sql` синхронизировать `schema.svg`/`schema.png`; когда схема стабилизируется,
  перейти на миграции — baseline прямо запрещает считать текущий черновик migration-ready.
- Коммит в `documentation/**` в ветке `main` пересобирает вики автоматически (workflow `docs → wiki`).
