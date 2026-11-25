# DocsApp

Сервис оформления документов: на входе Markdown или шаблон DOCX, на выходе DOCX / PDF / ODT с соблюдением
стилей — библиотека тем и коллекций стилей, извлечение стилей из готовых документов, валидация оформления
до рендера, публичный API с токенами.

Это точка входа в проектную документацию для разработчиков: что где лежит и что считается правдой.
Правила самого каталога — в [«Как вести документацию»](contributing.md), термины — в
[глоссарии](glossary.md), продуктовое намерение и инварианты — в
[`.agents/PROJECT.md`](https://github.com/DirtyDocsTeam/DocsApp/blob/main/.agents/PROJECT.md).

## Контур системы

Единственный вход — `Ingress` (HAProxy): REST/GraphQL идут в API, OIDC — в Keycloak, пути объектов — в
S3-шлюз.

- **Main API Plane** — `backend/api/`, Quarkus на JVM (Kotlin). Держит GraphQL и REST, задания и данные в
  PostgreSQL, проверяет токены Keycloak и раздаёт работы воркерам по gRPC.
- **S3 Gateway Plane** — `backend/s3-gateway/`, Go. Отдаёт статику и медиа: токен и путь объекта спрашивает
  у API по gRPC, в объектное хранилище ходит сам.
- **Воркеры** — отдельные деплойменты, а не модули API: `WorkerC` конвертация (C#), `WorkerV` валидация
  (C#/C++), `WorkerT` шаблоны (Python), `WorkerG` генерация стилей (Python). Внешняя LLM доступна только
  `WorkerG`.
- **Данные** — PostgreSQL (пользователи, токены, стили, задания, аудит) и SeaweedFS (исходники, вложения,
  результаты, статика). Клиент объектное хранилище напрямую не адресует.

Задание живёт дольше одного HTTP-запроса: API принимает файл, отвечает `202` с id и URL статуса и ставит
работу воркеру; воркер ведёт её через `QUEUED → PARSING → RENDERING → BUILDING → VALIDATING` до
терминального статуса, клиент опрашивает статус. Результат хранится 3 часа, вложения — 7 дней.

## Карта документации

| Раздел | Что внутри | Когда открывать |
|---|---|---|
| [`design/`](design/README.md) | C4-контекст, расшифровка контейнеров и связей, ERD (SVG + Mermaid), черновик DDL | меняете архитектуру или схему БД, ищете границу сервиса |
| [`api/`](api/index.md) | контракты REST, GraphQL и gRPC, собранные из кода | нужен контракт эндпоинта, схемы или `.proto` |
| [`md-spec/`](md-spec/README.md) | собственный диалект Markdown: рамка спецификации и эталоны GFM/GLFM | пишете парсер, валидатор или превью |
| [`research/`](research/README.md) | исследования под задачи: извлечение стилей из DOCX, перенос подхода «Книга в Markdown», PoC | выбираете подход и нужны проверенные цифры |
| [`qa/`](qa/README.md) | UserStory; тест-кейсы, чек-листы и отчёты ревью — пока пусто | проверяете приёмку или пишете тест-кейс |
| [`glossary.md`](glossary.md) | канонические термины предметной области | сомневаетесь, как называется сущность |
| [`contributing.md`](contributing.md) | как добавить страницу, что собирается скриптами, как обновляется вики | правите сам каталог документации |

## Что считается правдой

| Тема | Источник правды | Производные |
|---|---|---|
| Продукт: возможности, ограничения, безопасность, хранение | [`.agents/PROJECT.md`](https://github.com/DirtyDocsTeam/DocsApp/blob/main/.agents/PROJECT.md) | [`design/design.md`](design/design.md), глоссарий |
| Архитектура | C4-контекст [`design/context.drawio`](design/context.drawio): направление связи задаёт наконечник стрелки, а не подпись | расшифровка в [`design/design.md`](design/design.md); таблица связей там ведётся руками и может отставать — диаграмма важнее |
| Схема БД | Liquibase-чанжлог [`backend/api/src/main/resources/db/changelog`](https://github.com/DirtyDocsTeam/DocsApp/tree/main/backend/api/src/main/resources/db/changelog) | `design/db.sql` (`make db-schema`), ERD [`design/schema.svg`](design/schema.svg) и [`design/erd.md`](design/erd.md) (`make db-erd`) |
| Контракты API | код, аннотации и правила [`api-docs.toml`](https://github.com/DirtyDocsTeam/DocsApp/blob/main/api-docs.toml) | страницы `docs/api/` (`make api-docs`) |
| Термины | [`glossary.md`](glossary.md) | тексты всех разделов |

Руками не правятся `docs/api/**`, `design/db.sql`, `design/schema.svg` и `design/erd.md`: их
перезапишут сборки.

## Состояние проекта

- Система на ранней стадии: проверяйте предположения по коду, а не по документам.
- Схема БД — черновик: в исходном DDL неполные ограничения (статусы без `CHECK`, токены с уже истёкшим
  сроком), поэтому правда — чанжлог, а не `db.sql`.
- `docs/api/` — снимок того, что объявляет код сегодня, а не подписанный контракт.
- [`md-spec/`](md-spec/README.md) — пока рамка и примеры-эталоны: сам диалект не описан.
- Открытые решения и открытые вопросы собраны в
  [`PROJECT.md`](https://github.com/DirtyDocsTeam/DocsApp/blob/main/.agents/PROJECT.md) и
  [`design/design.md`](design/design.md).
