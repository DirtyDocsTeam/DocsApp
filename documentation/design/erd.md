# ERD: модель данных

Схема БД диаграммой. Источник правды — Liquibase-чанжлог
`backend/api/src/main/resources/db/changelog/`: из него собираются и [`db.sql`](db.sql), и диаграмма ниже
(`make db-schema`, `make db-erd`). Руками файл не правим — меняем чанжлог.

```mermaid
erDiagram
    api_tokens {
        bigint id PK
        bigint user_id FK
        varchar(128) token_hash
        timestamptz created_at
        timestamptz expires_at
        jsonb access
    }
    job_events {
        bigint id PK
        bigint job_id FK
        varchar(32) action
        jsonb data
    }
    job_media {
        bigint request_id PK, FK
        bigint media_id PK, FK
    }
    job_request {
        bigint id PK
        bigint parent_request_id FK
        varchar(64) external_id
        bigint processing_media_id FK
        varchar(4) input_type
        varchar(4) output_type
        varchar(32) type
        varchar(32) status
        bigint user_id FK
        bigint theme_id FK
        jsonb parameters
    }
    job_result {
        bigint id PK
        varchar(64) external_id
        bigint request_id FK
        bigint result_media_id FK
        timestamptz completed_at
    }
    media {
        bigint id PK
        boolean is_non_cacheable
        text mime_type
        text storage_path
        varchar(128) file_hash
        text public_path
        timestamptz created_at
        timestamptz updated_at
        timestamptz delete_at
    }
    styles {
        bigint id PK
        bigint theme_id FK
        varchar(32) type
        text example_text
        jsonb data
    }
    theme_collection_themes {
        bigint theme_collection_id PK, FK
        bigint theme_id PK, FK
    }
    theme_collections {
        bigint id PK
        text name
        boolean is_public
        jsonb parameters
        timestamptz created_at
        timestamptz updated_at
    }
    themes {
        bigint id PK
        text name
        boolean is_public
        jsonb parameters
        timestamptz created_at
        timestamptz updated_at
    }
    user_theme_collections {
        bigint user_id PK, FK
        bigint theme_collection_id PK, FK
        varchar(32) role
    }
    users {
        bigint id PK
        text oidc_token
        text email
        varchar(32)[] system_roles
        timestamptz created_at
        timestamptz updated_at
        bigint tokens
        timestamptz last_token_change_at
    }
    users ||--o{ api_tokens : "api_tokens.user_id"
    job_request ||--o{ job_events : "job_events.job_id"
    job_request ||--o{ job_media : "job_media.request_id"
    media ||--o{ job_media : "job_media.media_id"
    job_request |o--o{ job_request : "job_request.parent_request_id"
    media ||--o{ job_request : "job_request.processing_media_id"
    users ||--o{ job_request : "job_request.user_id"
    themes ||--o{ job_request : "job_request.theme_id"
    job_request ||--o{ job_result : "job_result.request_id"
    media ||--o{ job_result : "job_result.result_media_id"
    themes ||--o{ styles : "styles.theme_id"
    theme_collections ||--o{ theme_collection_themes : "theme_collection_themes.theme_collection_id"
    themes ||--o{ theme_collection_themes : "theme_collection_themes.theme_id"
    users ||--o{ user_theme_collections : "user_theme_collections.user_id"
    theme_collections ||--o{ user_theme_collections : "user_theme_collections.theme_collection_id"
```

## Связи

Внешние ключи в том виде, в каком они объявлены в схеме: `ребёнок.колонка` → `родитель.колонка`.

| Ребёнок | Колонка | Родитель | Колонка | Обязательная |
|---|---|---|---|---|
| `api_tokens` | `user_id` | `users` | `id` | да |
| `job_events` | `job_id` | `job_request` | `id` | да |
| `job_media` | `request_id` | `job_request` | `id` | да |
| `job_media` | `media_id` | `media` | `id` | да |
| `job_request` | `parent_request_id` | `job_request` | `id` | нет |
| `job_request` | `processing_media_id` | `media` | `id` | да |
| `job_request` | `user_id` | `users` | `id` | да |
| `job_request` | `theme_id` | `themes` | `id` | да |
| `job_result` | `request_id` | `job_request` | `id` | да |
| `job_result` | `result_media_id` | `media` | `id` | да |
| `styles` | `theme_id` | `themes` | `id` | да |
| `theme_collection_themes` | `theme_collection_id` | `theme_collections` | `id` | да |
| `theme_collection_themes` | `theme_id` | `themes` | `id` | да |
| `user_theme_collections` | `user_id` | `users` | `id` | да |
| `user_theme_collections` | `theme_collection_id` | `theme_collections` | `id` | да |
