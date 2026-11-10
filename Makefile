# DocsApp — короткие команды для документации и контрактов API.
#
#   make help           — список целей
#   make api-docs       — пересобрать контракты REST/GraphQL/gRPC в documentation/api/
#   make api-docs-check — проверить, что страницы контрактов соответствуют коду
#   make c4-relations   — перегенерировать таблицу связей C4 из context.drawio
#   make c4-check       — проверить, что таблица связей соответствует диаграмме
#   make docs-preview   — собрать вики локально в /tmp/wiki-dry, ничего не публикуя
#
# Нужен python3 (3.11+) — скрипты используют только стандартную библиотеку.

PYTHON ?= python3
API_DOCS := .github/scripts/api_docs.py
WIKI_SYNC := .github/scripts/wiki_sync.py
C4_RELATIONS := .github/scripts/c4_relations.py

.DEFAULT_GOAL := help

.PHONY: help api-docs api-docs-check c4-relations c4-check docs-preview

help: ## Показать этот список
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

api-docs: ## Собрать контракты REST/GraphQL/gRPC в documentation/api/
	$(PYTHON) $(API_DOCS)

api-docs-check: ## Проверить, что страницы контрактов соответствуют коду
	$(PYTHON) $(API_DOCS) --check

c4-relations: ## Обновить таблицу связей C4 в design.md из context.drawio
	$(PYTHON) $(C4_RELATIONS) --write

c4-check: ## Проверить, что таблица связей соответствует context.drawio
	$(PYTHON) $(C4_RELATIONS) --check

docs-preview: api-docs c4-relations ## Собрать вики в /tmp/wiki-dry без публикации
	$(PYTHON) $(WIKI_SYNC) --out /tmp/wiki-dry --no-dates
