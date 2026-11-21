# Подход «Книга в Markdown» — разбор и переносимость (issue #11)

**Задача:** [#11 «Изучить реализацию из "Книга в Markdown"»](https://github.com/DirtyDocsTeam/DocsApp/issues/11)
**Источник:** [habr.com/ru/articles/987982](https://habr.com/ru/articles/987982/) — «Книга в Markdown: Автоматическая сборка
статического сайта mdBook и файла DOCX с оформлением по ГОСТ», автор `worldbeater`, опубликовано 2026-01-23 10:10 UTC.
**Первоисточник кода:** [true-grue/kisscm](https://github.com/true-grue/kisscm) (курс «Конфигурационное управление»,
РТУ МИРЭА), второй пример — [true-grue/kisport](https://github.com/true-grue/kisport) (`true-grue.github.io/kisport`).
**Контекст команды:** комментарий `Alexander1248` в #11 — «способ используется норм, но инструментарий такой себе,
мы примерно по такому же пойдём, но не через pandoc». Этот отчёт — ответ на вопрос «что именно pandoc делает за нас
и что придётся написать самим».
**Метод:** обзор по исходникам (статья + все файлы конвейера `kisscm` + чтение `template.docx` как zip/XML).
**Сборка книги локально не запускалась** — что проверено, что нет, см. §7.

---

## 1. TL;DR — что делать

1. **Подход = «один Markdown-источник → три выхода» на одном AST.** `book.md` (или 45 файлов `md/*.md`, склеенных
   в один поток) → pandoc AST → 6 фильтров → три писателя: DOCX (ГОСТ-шаблон), PDF, mdBook-сайт. Ценность не в pandoc,
   а в **архитектуре**: одна модель + набор проходов + разные выходы. Это ровно наша схема `job_request` → `job_result`
   для `docx`/`pdf`/`odt`/`html`.
2. **Половина нашего конвейера уже совпадает с их «темой».** `--reference-doc=template.docx` — это не магия pandoc,
   а копирование частей шаблона (`word/styles.xml`, `word/theme/theme1.xml`, `word/numbering.xml`, `word/fontTable.xml`,
   `w:sectPr`, колонтитулы) в выходной zip + подстановка `pStyle` в абзацы. Наш PoC по #8 читает **те же самые части** —
   значит «тема = DOCX-шаблон» у нас уже вход, и его надо сделать ещё и выходом (US-13, экспорт).
3. **Без pandoc дорогими оказываются ровно два узла:** LaTeX → OMML (формулы) и DOCX-writer с шаблоном. Дёшево:
   markdown-парсер, AST-проходы, нумерация/перекрёстные ссылки, разрывы страниц, регистр, «изображения как код».
   Средне: CSL/список литературы по ГОСТ Р 7.0.5-2008 (лучше не писать самим, а взять citeproc).
4. **Их `template.docx` — не ГОСТ 7.32-2017** (проверено чтением файла): страница Letter 215.9 × 279.4 мм, поля
   20/20/20/20 мм, межстрочный 1.3, абзацный отступ 10 мм, TNR 14 pt. Эталон #8 (`report-732-2017`): A4, 30/15/20/20 мм,
   1.5, 12.5 мм. То есть **переносить надо механизм, а не файл**: у них шаблон под требования издательства, у нас — под ГОСТ.
5. **PDF через `docx2pdf` — тупик для нас** (требует установленного Microsoft Word, Windows/macOS). Наш путь — LibreOffice
   headless, он уже проверен в #8 (`HOME=/tmp` + `-env:UserInstallation=file:///tmp/loprof`).
6. **Готовый DOCX почти всегда дорабатывают пост-обработкой XML.** У них для замены маркера списка `•` → `–` (ГОСТ-тире)
   есть отдельный скрипт `tools/bullets.py`, который перепаковывает zip и правит `word/numbering.xml`. Это независимое
   подтверждение вывода #8 (доля прямого форматирования 0.516 в ГОСТ-шаблоне): финальный проход по OOXML нужен всем.
7. **Мелочи, которые стоит забрать бесплатно:** регистр заголовков и разрыв страницы как декларативные проходы по AST
   (а не ручная правка); имя файла картинки = sha1 от её содержимого (дедуп); орфопроверка (hunspell) как стадия
   валидации; `make`-таргеты как стадии пайплайна (у нас — `job_events`).
8. **Отчёт не закрывает вопрос «делать ли»**: #9 (стек) и #12 (UI) всё ещё открыты, поэтому §8 — открытые вопросы
   к команде, а не план реализации.

---

## 2. Что именно сделано в первоисточнике (проверено по файлам)

Статья — 6 разделов (простая книга → нумерация/стили → изображения как код → PDF → mdBook → сборочный скрипт).
Репозиторий `kisscm` содержит больше, чем статья:

| Файл | Роль | Детали (проверено) |
|---|---|---|
| `contents` | список исходников книги | 45 файлов `md/*.md`, сгруппированы в `INTRO/CLI/MAN/VCS/LANGS/BUILD/VM/DOCS/EXAM/BIB`, переменная `MD` |
| `makefile` | сборка | `all: spellcheck docx pdf web`, таргеты `install-pandoc`/`install-pandoc-crossref`/`install-mdbook`/`install-graphviz`, ветки Windows/Unix |
| `default.yaml` | метаданные pandoc | `toc-title`, `bibliography: bibliography.bib`, `link-citations: true`, `csl: gost-r-7-0-5-2008-numeric-iaa.csl` |
| `crossref-docx.yaml` | pandoc-crossref для DOCX | `numberSections: true`, `sectionsDepth: 3`, `secHeaderDelim: .&nbsp;`, `figureTitle/figPrefix`, `tableTitle/tblPrefix`, `tableEqns: true`, `eqnPrefixTemplate: ($$i$$)`, `eqnBlockTemplate` с сырым OOXML |
| `crossref.yaml` | то же для сайта | те же ключи без `eqnBlockTemplate` |
| `template.docx` | тема оформления | 25 частей zip, 102 стиля, разбор — §4 |
| `bibliography.bib` | источники | BibTeX, 9.8 КБ |
| `gost-r-7-0-5-2008-numeric-iaa.csl` | стиль списка литературы | взят из GOSTdown (13.6 КБ) |
| `tools/upper.lua` | проход AST | H1 → верхний регистр + `\newpage` перед каждым H1 |
| `tools/pagebreak.lua` | проход AST | сторонний (pandoc-ext), `\newpage` → `<w:p><w:r><w:br w:type="page"/></w:r></w:p>` |
| `tools/pysvg.lua` + `tools/pysvg.py` | изображения как код | `CodeBlock.pysvg` → python → SVG → `pandoc.mediabag`, имя файла = `pandoc.sha1(svg)` |
| `tools/mdbook.lua` | проход AST для сайта | `InlineMath` → `\(x\)`, `csl-entry` → `<p id="…">`, раскрытие `Div`, `#…`-ссылки → `biburl#…` |
| `tools/bullets.py` | **пост-обработка DOCX** | правит `word/numbering.xml`: `w:val="•"` → `w:val="–"`, перепаковывает zip |
| `tools/mdbook.py` | разбиение книги на страницы | H1/H2 → отдельные `.md` + `SUMMARY.md`, имя файла через транслитерацию `iuliia` |
| `tools/doc2pdf.py` | PDF | `docx2pdf.convert` (MS Word через API) |
| `tools/spellcheck.py` + `excluded.txt` | валидация текста | hunspell по `md/`, исключения — 64 слова |
| `book.toml` | mdBook | `src = build/src`, `build-dir = build/book`, `mathjax-support`, `no-section-label` |
| `.github/workflows/main.yml` | CI | `pip install docx2pdf iuliia` → `make install` → `make web` → sitemap → GitHub Pages |

Версии, закреплённые в `makefile`: pandoc **3.8.3**, pandoc-crossref **0.3.18.1**, mdBook **0.5.1**, Python ≥ 3.12,
graphviz из apt, плюс `docx2pdf` и `iuliia` из PyPI. Заметно: `install-pandoc` скачивает **linux-amd64** архив, а все
команды в статье вызывают `tools/pandoc.exe` — сценарий авторов Windows-ориентированный, Linux поддержан «наполовину».

---

## 3. Конвейер по шагам

### 3.1. Вход и диалект markdown
`BASE_OPTIONS` задаёт важное: `--from=markdown+tex_math_single_backslash+tex_math_dollars+raw_tex`, `--columns=1`,
`--resource-path=images`, `--toc`. То есть вход — это **markdown + LaTeX-формулы + сырой TeX-код** (`\newpage`),
а не CommonMark. `--columns=1` (не переносить строки) — иначе diff в git «шумит»; это прямая реализация «Docs as Code».

### 3.2. Нумерация и перекрёстные ссылки
`pandoc-crossref` даёт сквозные счётчики разделов (до 3 уровней), рисунков, таблиц, формул и ссылки на них:
`$$ … $$ {#eq:leven}` → `@eq:leven` → «(1)» в тексте; `{#fig:levio .pysvg caption="…"}` → «рис. 1»;
`{-}` у заголовка отключает нумерацию. Формула с номером собирается через `eqnBlockTemplate`: центр по табу,
номер — по правому табу. Позиции табов заданы **абсолютно** (`w:pos="4680"` и `"9960"` twips) — см. §4.3.

### 3.3. Тема оформления: `--reference-doc=template.docx`
Единственный источник «дизайна». Практический вывод для нас: тема — это файл DOCX, а не набор настроек в коде.
Из шаблона в выход переезжают `styles.xml`, `theme1.xml`, `numbering.xml`, `fontTable.xml`, `settings.xml`, `sectPr`
(формат страницы, поля, колонтитулы) и встроенные media. Стили сопоставляются **по имени** (`w:name`), поэтому
имена в шаблоне должны остаться ровно теми, которые ищет писатель (`Body Text`, `First Paragraph`, `Compact`,
`Source Code`, `heading 1..9`, `Image Caption`, `Table Caption`, `Block Text`, `Footnote Text`).

### 3.4. Проходы по AST
- `upper.lua`: H1 → `Str` в верхний регистр, но только `if el.level == 1 and FORMAT == 'docx'`; в том же файле
  `Blocks()` вставляет `RawBlock("tex", "\\newpage")` перед каждым H1 (в статье версия **без** guard по `FORMAT` —
  в репозитории guard добавлен, иначе сайт получал бы капс).
- `pagebreak.lua` (pandoc-ext, MIT-подобная лицензия ISC): единственная задача — превратить `\newpage` в формат выхода.
  Подменяемая таблица форматов (`ooxml`, `odt`, `html`, `latex`, `typst`, …) — хороший пример «транспорт-независимой»
  директивы.
- `pysvg.lua`/`pysvg.py`: `CodeBlock` с классом `pysvg` → запуск `python -` → SVG в mediabag. Имя файла — sha1 от
  содержимого SVG (автоматический дедуп и кэш), атрибуты блока кода (`width`, `id`, `caption`) переезжают в рисунок.
  Ничего специфичного для pandoc в самой идее нет.
- `mdbook.lua`: четыре адаптации под mdBook — inline-математика в `\(x\)`, `csl-entry` → `<p id="…">` (чтобы работали
  ссылки на источники), раскрытие `Div`-обёрток, переписывание `#…`-ссылок на страницу списка литературы.

### 3.5. Цитирование
BibTeX + CSL-стиль `gost-r-7-0-5-2008-numeric-iaa.csl` + `--citeproc` + `link-citations: true` → нумерованный
список литературы по ГОСТ Р 7.0.5-2008 с кликабельными переходами из текста. Формат BibTeX выбран потому, что
Google Scholar/Истина отдают ссылки именно в нём. Для нас это отдельная тема (`themes`?), но важно: **список
литературы по ГОСТ — это CSL-файл**, а не код; его можно взять как данные.

### 3.6. PDF
`tools/doc2pdf.py` — две строки поверх `docx2pdf`, который дёргает **Microsoft Word** через COM/AppleScript.
На Linux и в CI это не работает (CI ставит `docx2pdf`, но собирает только `web` — то есть зависимость в workflow
лишняя). Наш эквивалент уже проверен: `soffice --headless --convert-to pdf` + `pdffonts` как оракул шрифтов (#8).

### 3.7. Сайт
mdBook получает **не** исходный `book.md`, а пересобранный pandoc-ом markdown (`--to=markdown-…` с выключенными
таблицами-расширениями и включённым `hard_line_breaks`), разложенный `mdbook.py` по страницам с `SUMMARY.md`.
Транслитерация имён файлов — через `iuliia` (лишняя зависимость на ровном месте: достаточно было бы слага).

### 3.8. Пост-обработка DOCX
`bullets.py` открывает готовый `.docx` как zip, в `word/numbering.xml` заменяет `w:val="•"` на `w:val="–"` и
перепаковывает. Проверено по файлу: в `template.docx` в `numbering.xml` уже есть и `•` (5 вхождений), и `–` (4) —
то есть маркер списка приходит не только из шаблона, а генерируется писателем, и единственный способ привести его
к ГОСТ — правка XML после сборки.

### 3.9. Сборка и CI
`make docx | pdf | web | serve | all | clean | install-*`; `all` включает `spellcheck`. CI (`.github/workflows/main.yml`)
на push в `main`: `make web` → sitemap → `upload-pages-artifact` → `deploy-pages`. То есть **артефакт сайта
воспроизводим из репозитория одной командой** — это и есть главный практический выигрыш подхода.

---

## 4. Проверенный разбор `template.docx`

### 4.1. Что внутри файла (25 частей zip)

| Параметр | Значение | Где |
|---|---|---|
| Размер страницы | `pgSz w=12240 h=15840` twips = **215.9 × 279.4 мм (Letter)** | `document.xml/sectPr` |
| Поля | `pgMar top=right=bottom=left=**1134**` twips = **20 мм со всех сторон**; `header/footer=720` (12.7 мм) | там же |
| `docDefaults` | `rFonts asciiTheme="minorHAnsi"`, `sz=24` (12 pt), `spacing after=200` | `styles.xml` |
| `Normal` (`styleId=a1`, default) | Times New Roman, `sz=28` (**14 pt**), `line=312 lineRule=auto` (**1.3**), `jc=both`, `after=0` | `styles.xml` |
| `Body Text` (`a2`) | basedOn `Normal`, `ind firstLine=567` twips = **10.0 мм** | `styles.xml` |
| `heading 1` (`1`) | `sz=30` (15 pt), `b`, `jc=center`, `after=360` (18 pt), `outlineLvl=0` | `styles.xml` |
| `heading 2` (`21`) | `szCs=28`, `before/after=360`, `jc=center`, `outlineLvl=1` | `styles.xml` |
| `heading 3` (`30`) | `before=360`, `ind left=567`, `jc=left`, `b+i`, `outlineLvl=2` | `styles.xml` |
| `Source Code` | Consolas, `sz=22` (11 pt), `before/after=120`, `jc=left` | `styles.xml` |
| `Image Caption` / `Table Caption` | basedOn `caption`, `sz=26` (13 pt), `jc=center` / `jc=right` | `styles.xml` |
| Стилей всего | **102**: paragraph 51, character 47, table 3, numbering 1 | `styles.xml` |
| Нумерация | 12 `abstractNum`, 65 `num` | `numbering.xml` (20 КБ) |
| Колонтитулы | 3 header + 3 footer (`first/even/default`), `PAGE`-поле — в `footer2.xml` | `header*.xml`, `footer*.xml` |
| Прочее | `theme1.xml`, `fontTable.xml`, `settings.xml`, `word/media/image1.png` (76 КБ), `docProps/app.xml` → «Microsoft Office Word 16.0000» |  |

### 4.2. Сверка с ГОСТ 7.32-2017 (эталон #8)

| Требование | ГОСТ 7.32-2017 / `report-732-2017` | `template.docx` из kisscm | Вывод |
|---|---|---|---|
| Формат страницы | A4 210 × 297 мм | Letter 215.9 × 279.4 мм | **не соответствует** |
| Поля | 30 / 15 / 20 / 20 мм | 20 / 20 / 20 / 20 мм | **не соответствует** |
| Шрифт тела | Times New Roman 14 pt | TNR 14 pt | соответствует |
| Межстрочный | 1.5 (360 twips auto) | 1.3 (312 twips auto) | **не соответствует** |
| Абзацный отступ | 12.5 мм | 10.0 мм | **не соответствует** |
| Выравнивание | по ширине | `jc=both` | соответствует |

Вывод: шаблон собран под «ГОСТ + требования издательства» (статья это и заявляет: «соответствия ГОСТ и требованиям
издательства, с которым мы сотрудничали»), а не под ГОСТ 7.32-2017. Для DocsApp он годится как **пример структуры
файла-темы**, но не как готовый ГОСТ-пресет.

### 4.3. Ловушки шаблона, важные для нашей реализации

1. **`styleId` не совпадает с именем**: `Normal = a1`, `Body Text = a2`, `caption = af1`, `heading 1 = 1`,
   `heading 2 = 21`, `heading 3 = 30`, `List Bullet = a0`. Сопоставлять можно только по `w:name`.
2. **Имена части стилей локализованы**: рядом с ASCII-именами встроенных стилей живут `Заголовок Знак`,
   `Основной текст Знак`, `Нижний колонтитул Знак`, `Красная строка Знак`, `Стиль1`. Если Word сохранит
   локализованными и имена **абзацных** встроенных стилей (`Заголовок 1` вместо `heading 1`), маппинг
   писателя сломается молча → нужен фолбэк по `outlineLvl`/`styleId` + предупреждение (та же проблема, что в #8).
3. **Абсолютные позиции табов формул привязаны к геометрии Letter.** `eqnBlockTemplate` ставит табы на
   4680 и 9960 twips. Ширина текста в шаблоне: 12240 − 2 × 1134 = **9972** twips, то есть правый таб почти
   точно по правому полю. Для A4 с полями 30/15 ширина текста = 9354 twips, и таб 9960 окажется на
   (9960 − 9354) × 0.01764 ≈ **10.7 мм правее** текстового блока. Цифры посчитаны, но не отрендерены (см. §7):
   при смене темы на ГОСТ `eqnBlockTemplate` надо пересчитывать или задавать в процентах.
4. **`Compact`, `First Paragraph`, `Image Caption` объявлены `customStyle="1"`** — писатель их найдёт по имени,
   но в UI Word они не «встроенные»: пользователь, правящий тему, увидит их в разделе пользовательских стилей.

---

## 5. Что делает pandoc и чем это заменить без pandoc

| Узел конвейера | В kisscm | Замена без pandoc | Цена / риск |
|---|---|---|---|
| Разбор markdown + yaml + div/span/`{=openxml}` | pandoc reader | `markdown-it-py` (Python), `goldmark` (Go), `markdown-it` (JS), `mdast`/`remark` | **низкая**: расширения придётся объявить самим (математика, атрибуты, ссылки) |
| AST и проходы (регистр, разрывы, `Div`, `Link`, `Math`) | Lua-фильтры | обычные visitor-проходы по своей модели | **низкая**, кода меньше, чем в Lua-версиях |
| Счётчики и перекрёстные ссылки | pandoc-crossref | свой реестр меток: `label → (тип, номер)` + проход нумерации + проход подстановки | **средняя**: нужны правила «рисунок 1 — Название», «(1)», «табл. 2», ошибки (дубли/битые ссылки) в валидацию |
| Тема оформления (`--reference-doc`) | копирование частей шаблона | то же самое: наш writer берёт `styles/theme/numbering/fontTable/sectPr/headers/footers` из темы и подставляет `pStyle` | **средняя**: у нас уже есть читатель этих частей (#8 PoC), нужен писатель `document.xml` |
| Формулы LaTeX → OMML | встроенный texmath | (а) порт texmath-подобного конвертера; (б) `latex2mathml` + XSLT `MML2OMML.XSL`; (в) рендер формулы в SVG/PNG и вставка картинкой | **высокая**: (в) — компромисс без редактируемости в Word, (б) — лицензия на XSL от Office, (а) — самый дорогой путь |
| Список литературы по ГОСТ | `--citeproc` + CSL | `citeproc-py`/`citeproc-rs`, либо отдельный сервис; CSL-файл берём как данные | **средняя**, но её можно вынести за MVP |
| Встраивание картинок | `pandoc.mediabag` | наш `media`/`job_media` — уже есть | **низкая** |
| DOCX → PDF | `docx2pdf` + MS Word | `soffice --headless --convert-to pdf` (наш проверенный путь) | **низкая** (но +1 сервис и версия LO в контракте) |
| Разбиение книги на страницы для веба | `mdbook.py` + `iuliia` | нам не нужно, если нет HTML-выхода; транслитерация — 20 строк | **низкая** |

Ключевой архитектурный вывод: **pandoc в этом конвейере — это «AST + фильтры + два писателя + citeproc + texmath»**.
Из этого списка уникально тяжёлыми являются только `texmath` и docx-writer; остальное — обычная работа.

---

## 6. Что забрать в DocsApp (решения, не код)

1. **Тема = DOCX-шаблон, в обе стороны.** У kisscm шаблон только вход; у нас по ТЗ нужен и импорт (#8), и экспорт
   (US-13). Импорт и экспорт должны описывать **один** JSON (`themes.parameters` + `styles`), иначе round-trip
   «шаблон → тема → шаблон» будет расходиться.
2. **Одна модель — много выходов.** `job_request.format ∈ {docx, pdf, odt, html}`; стадии конвейера = `job_events`
   (`PARSING → NUMBERING → WRITING → POSTPROCESS → CONVERTING`), как `make`-таргеты у них.
3. **Нумерация и перекрёстные ссылки — отдельный проход с реестром меток.** Ошибки (дубль метки, ссылка в никуда,
   нумерация без заголовка) — в отчёт валидации, а не молча в вывод. У них это делает `pandoc-crossref` и молчит.
4. **Свои декларативные директивы вместо `raw_tex`/`{=openxml}`.** `\newpage` и «H1 капсом» у нас должны быть
   маркерами модели (`pagebreak`, `caps`) — иначе в пользовательский markdown протекает TeX/XML, а это и
   поверхность атаки (инъекция сырого OOXML в документ), и невозможность валидации.
5. **Постпроход по готовому DOCX обязателен.** `bullets.py` — минимальный пример (маркер списка `•` → `–`).
   У нас тот же инструмент нужен шире: `numbering.xml`, `fontTable.xml`, поля/закладки, `settings.xml`. Плюс
   это значит, что «DOCX-writer» у нас — не «с нуля», а «шаблон + подстановка контента + патч XML».
6. **Формулы: решить до реализации.** OMML (редактируемо в Word) против картинки (просто). От этого зависит
   объём работ и требования ТЗ — это вопрос к команде (§8).
7. **PDF только через LibreOffice.** `docx2pdf` требует MS Word; их CI ставит его «на всякий случай».
8. **Валидация как стадия, а не как пожелание.** У них `make spellcheck` (hunspell + `excluded.txt` на 64 слова)
   стоит в `all`. У нас стадия валидации уже в ТЗ — из их подхода берём идею «словарь исключений = данные репозитория».
9. **«Изображения как код»** (mermaid/graphviz → SVG, имя = хэш содержимого) — приятная фича для отчётов и
   диаграмм, ложится на `media` + `job_media`; в MVP не обязательна, но дешева.
10. **Веб-выход** (mdBook-аналог) — только если он есть в ТЗ; иначе `html`-формат не нужен, а `mdbook.py`-разбиение
    и `iuliia` не переносим.

---

## 7. Ограничения этого обзора (что проверено, а что нет)

**Проверено:**
- статья и её структура, автор, дата (HTML-страница);
- все файлы конвейера `kisscm` прочитаны (`makefile`, `contents`, yaml-конфиги, все 10 файлов `tools/`, workflow, `book.toml`, `README`);
- `template.docx`: состав zip, `sectPr` (`pgSz`/`pgMar`), `docDefaults`, 102 стиля с `styleId`/`name`/`basedOn`/`pPr`/`rPr`,
  `numbering.xml` (12 `abstractNum` / 65 `num`, вхождения `•` и `–`), 3 header + 3 footer, `PAGE`-поле в `footer2.xml`,
  `app.xml`;
- арифметика размеров в мм/пт от twips (1 twip = 1/1440″ = 0.01764 мм), 240-е доли строки.

**Не проверено (и помечено в тексте как предположение):**
- **сборка книги не запускалась**, поэтому неизвестно, какие именно `pStyle` получает выходной `document.xml`,
  как выглядит сгенерированный pandoc-ом `numbering.xml` (и потому — обязателен ли `bullets.py` на выходе
  или он страхует от темы), как рендерятся формулы с `eqnBlockTemplate` и не выезжает ли номер за поля;
- утверждение «pandoc пишет свой `numbering.xml`, а не наследует из шаблона» — вывод из наличия `bullets.py`,
  а не из прогона;
- утверждение «локализованные имена встроенных стилей ломают маппинг» — вывод из #8 и из локализованных
  character-стилей в этом шаблоне; на абзацных стилях этого файла имена английские, то есть на нём проблема
  **не воспроизводится**;
- поведение `docx2pdf` и `mdbook` не проверялось (не нужны для решения по DocsApp);
- второй пример (`kisport`) не разбирался — существование репозитория подтверждено (HTTP 200), конвейер не читался.

---

## 8. Открытые вопросы к команде

1. **DOCX-writer: пишем сами или «шаблон + патч»?** Второй вариант дешевле и ближе к нашему #8-PoC, но ограничивает
   вёрстку (сложные таблицы/многоколоночные секции), надо решать до оценки #11.
2. **Формулы: OMML или картинка?** Влияет на ТЗ и на объём (это главный риск переноса «без pandoc»).
3. **Список литературы по ГОСТ Р 7.0.5-2008** — своя CSL-обвязка или зависимость `citeproc`? Если своя — это
   отдельная задача, не часть #11.
4. **Нужен ли HTML/веб-выход** в продукте (у них — mdBook)? Если да, это `job_result.format='html'` и своя разбивка.
5. **Объём #11:** у задачи `Priority=High`, `Effort=Medium`, `Target date=2026-10-28`. Этот отчёт закрывает
   «изучить»; нужен ли в этом же спринте прототип (например, «markdown → DOCX по ГОСТ-шаблону» на нашем стеке) —
   решает команда.

---

## Приложение A. Файлы и воспроизведение

```
docs/research/book-to-markdown-approach.md   — этот отчёт
```

Что читалось (файлы первоисточника, ветка `main`):

```bash
BASE=https://raw.githubusercontent.com/true-grue/kisscm/main
for f in makefile contents default.yaml crossref-docx.yaml crossref.yaml book.toml README.md \
         tools/upper.lua tools/pagebreak.lua tools/pysvg.lua tools/pysvg.py \
         tools/mdbook.lua tools/mdbook.py tools/bullets.py tools/doc2pdf.py \
         tools/spellcheck.py excluded.txt .github/workflows/main.yml template.docx; do
  curl -sSL "$BASE/$f" -o "$(basename "$f")"
done
```

Как разбирался `template.docx` (только stdlib, без сборки книги):

```bash
python3 - <<'EOF'
import zipfile, re
z = zipfile.ZipFile('template.docx')
doc = z.read('word/document.xml').decode()
print(re.search(r'<w:sectPr.*?</w:sectPr>', doc, re.S).group(0))   # pgSz / pgMar
st = z.read('word/styles.xml').decode()
for m in re.finditer(r'<w:style ([^>]*)>(.*?)</w:style>', st, re.S):  # type/styleId/name/pPr/rPr
    print(m.group(1))
EOF
```

Тот же результат в удобном виде даёт PoC из #8 (он читает те же части, что берёт pandoc из reference-doc):

```bash
python3 docs/research/poc/docx_style_extract.py template.docx -o /tmp/kisscm-theme.json
```

## Приложение B. Источники

- [«Книга в Markdown» (Habr, 987982)](https://habr.com/ru/articles/987982/) — статья, 6 разделов, автор `worldbeater`.
- [true-grue/kisscm](https://github.com/true-grue/kisscm) — первоисточник конвейера; [онлайн-версия](https://true-grue.github.io/kisscm/); [true-grue/kisport](https://github.com/true-grue/kisport) — второй пример.
- [jgm/pandoc](https://github.com/jgm/pandoc), [lierdakil/pandoc-crossref](https://github.com/lierdakil/pandoc-crossref), [pandoc-ext/pagebreak](https://github.com/pandoc-ext/pagebreak), [rust-lang/mdBook](https://github.com/rust-lang/mdBook).
- [ГОСТdown](https://gitlab.iaaras.ru/iaaras/gostdown) — источник CSL `gost-r-7-0-5-2008-numeric-iaa.csl` (в статье и в `README` kisscm).
- ГОСТ 7.32-2017 (поля 30/15/20/20, TNR 14, 1.5, отступ 12.5 мм) — эталонные значения из #8, шаблон `report-732-2017`.
- ECMA-376 / ISO 29500-1: `CT_SectPr` (§17.6.17), `CT_Style` (§17.7.4.17), `CT_Num`/`CT_AbstractNum` (§17.9) — для чтения `sectPr`/`styles.xml`/`numbering.xml`.
- [docx2pdf](https://pypi.org/project/docx2pdf/) — преобразование через Microsoft Word (ограничение платформы).
