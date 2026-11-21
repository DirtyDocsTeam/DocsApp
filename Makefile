# DocsApp — короткие команды для документации и контрактов API.
#
#   make help           — список целей
#   make api-docs       — пересобрать контракты REST/GraphQL/gRPC в documentation/api/
#   make api-docs-check — проверить, что страницы контрактов соответствуют коду
#   make db-schema      — пересобрать documentation/design/db.sql из Liquibase-чанжлога
#   make db-check       — проверить, что db.sql соответствует чанжлогу
#   make db-erd         — пересобрать ERD (SVG + Mermaid) из Liquibase-чанжлога
#   make db-verify      — прогнать db.sql на чистой PostgreSQL в docker
#   make docs-preview   — собрать вики локально в /tmp/wiki-dry, ничего не публикуя
#
# Нужен python3 (3.11+) — скрипты используют только стандартную библиотеку.

PYTHON ?= python3
API_DOCS := .github/scripts/api_docs.py
WIKI_SYNC := .github/scripts/wiki_sync.py
DB_SCHEMA := .github/scripts/db_schema.py

.DEFAULT_GOAL := help

.PHONY: help api-docs api-docs-check db-schema db-check db-erd db-verify docs-preview

help: ## Показать этот список
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

api-docs: ## Собрать контракты REST/GraphQL/gRPC в documentation/api/
	$(PYTHON) $(API_DOCS)

api-docs-check: ## Проверить, что страницы контрактов соответствуют коду
	$(PYTHON) $(API_DOCS) --check

db-schema: ## Пересобрать documentation/design/db.sql из Liquibase-чанжлога
	$(PYTHON) $(DB_SCHEMA)

db-check: ## Проверить, что db.sql соответствует чанжлогу
	$(PYTHON) $(DB_SCHEMA) --check

db-erd: ## Пересобрать ERD: SVG и Mermaid из Liquibase-чанжлога
	$(PYTHON) $(DB_SCHEMA) --render

db-verify: ## Прогнать db.sql на чистой PostgreSQL в docker
	$(PYTHON) $(DB_SCHEMA) --verify

docs-preview: api-docs ## Собрать вики в /tmp/wiki-dry без публикации
	$(PYTHON) $(WIKI_SYNC) --out /tmp/wiki-dry --no-dates
