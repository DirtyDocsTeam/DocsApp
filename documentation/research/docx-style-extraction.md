# Извлечение стилей из DOCX — исследование (issue #8)

**Задача:** [#8 «Исследовать как вытягивать стили из docx файлов»](https://github.com/DirtyDocsTeam/DocsApp/issues/8)
**Контекст:** ТЗ (issue #7, п. 3 «подгонка документа к стилю»), компонент *A — «Извлечение стилей из DOCX»*, `db.sql` → `themes` / `theme_collections` / `styles`, issue #11 (реализация из «Книга в Markdown», без Pandoc).
**Артефакты исследования:** `docs/research/poc/docx_style_extract.py` (рабочий PoC, stdlib), образцы: ГОСТ-шаблон `report-732-2017` (Microsoft Word 16, 64 стиля), `pandoc.docx` (pandoc 3.1.11.1), `test.docx` (Mac Word 14).
**Проверено на:** LibreOffice 25.2.3.2, Python 3.13.5, python-docx 1.2.0, pandoc 3.1.11.1.

---

## 1. TL;DR — что делать

1. **Основной путь — прямой разбор OOXML.** DOCX = zip (OPC) + XML. Стили лежат в `word/styles.xml`, шрифты темы — в `word/theme/theme1.xml`, списки — в `word/numbering.xml`, параметры страницы — в `sectPr` внутри `word/document.xml`. Тяжёлые зависимости не нужны: PoC на `zipfile` + `xml.etree` — ~950 строк, **87 мс** на файл 1.1 МБ (2285 прогонов), полный контроль над моделью.
2. **Извлекать надо две вещи, а не одну.** (а) *стили* — `styles.xml` + разрешение наследования; (б) *оформление по факту* — мода фактических `rPr`/`pPr` по телу документа. В реальном ГОСТ-шаблоне только **78 %** абзацев имеют `pStyle`, и `Normal` не используется **ни разу** — по одному `styles.xml` вы получите «Calibri 11 pt», а документ на самом деле «Times New Roman 14 pt, 1.5, отступ 12.5 мм, по ширине». Обе выжимки уже считаются в PoC (`effectiveStyles`, `dominantFormatting`).
3. **Обязателен слой маппинга стиль → каноническая роль** (`heading1..N`, `body`, `figureCaption`, `tableText`, `tocN`, …) и экран подтверждения маппинга в UI: в живых файлах `styleId` — мусор (`aff9`, `31`, `1`), а имена локализованы (`Раздел`, `Подраздел`, `Название рисунка`). В PoC автомат закрывает **98 %** стилизованных абзацев ГОСТ-шаблона, остаток — ручное подтверждение.
4. **LibreOffice headless — вспомогательный, но очень полезный инструмент:** нормализация «грязного» входа (`.doc`, `.docm`, ODT/RTF, экспорт Google Docs) через `soffice --convert-to docx` и **оракул для валидации** (рендер в PDF + `pdffonts`: так проверено, что вытянутые из шаблона параметры совпадают с реальным рендером). Ограничение проверено: при docx-экспорте LO **«уплощает» оформление** — все прогоны получают прямое `rPr` (21 из 21 в контрольном файле, доля прямого форматирования 0.83). Поэтому LO — нормализатор формата входа и оракул, но не источник стилей.
5. **Pandoc не переносит стили исходного документа.** Он пересобирает файл по своему `reference.docx`: round-trip `test.docx` дал 38 → 70 стилей (свои, пересечение с исходником — 6 служебных имён), а параметры страницы (`sectPr`) в выходе **отсутствуют вовсе** (`page: {}`). В собственных выходных файлах pandoc доля прямого форматирования — 0.22. Как источник стилей не годится; вывод «Pandoc-конвейер нестабилен» (issue #11) подтверждается.
6. **Библиотеки — только если нужен полный редактор docx.** Для извлечения стилей они дают мало (python-docx, например, вообще отказывается открывать `.docm` — проверено), а Go-варианты с чтением стилей (`unioffice`, `fumiama/go-docx`) — AGPL/коммерция, что для сетевого SaaS плохо совместимо.

---

## 2. Что понимаем под «вытянуть стили»

Из `db.sql` и диаграммы архитектуры следуют три сценария, и им нужны разные выжимки:

| Сценарий | Что нужно из DOCX | Куда в модели |
|---|---|---|
| Импорт стиля из готового документа («сделай как в этом ГОСТ-отчёте») | параметры страницы, шрифты/размеры/интервалы/отступы по ролям, нумерация, стили таблиц/подписей | `themes.parameters` + `styles(type='render')` |
| Подгонка входящего документа к выбранному стилю (US-06, валидация) | карта «стиль документа → роль» + допуски | `styles(type='transform')` + отчёт валидации |
| Экспорт стиля (US-13) | обратная операция: тема → `reference.docx` / `.dotx` | шаблон DOCX |

Ключевое ограничение: **из DOCX нельзя «вытянуть» то, чего в нём нет как стиля.** ГОСТ-шаблон «на глаз» оформлен верно, но половина форматирования — прямое (`w:rPr` на прогонах). Поэтому в модели темы нужны *и* именованные стили, *и* статистика фактического оформления, а в UI — предупреждение «стиль восстановлен по фактическому оформлению, проверьте».

---

## 3. Анатомия DOCX: где что лежит

DOCX — OPC-контейнер (zip), внутри — части XML. Для задачи релевантны:

| Часть | Что содержит | Нужно |
|---|---|---|
| `word/styles.xml` | `docDefaults` (базовые `rPr`/`pPr`), `latentStyles` (декларация 371 «спящего» встроенного стиля), `w:style` (id, name, basedOn, next, link, qFormat, pPr, rPr, tblPr, tblStylePr) | **да, ядро** |
| `word/theme/theme1.xml` | `fontScheme` (major/minor: latin/ea/cs + `script`-переопределения), `clrScheme` (dk1/lt1/accent1..6/hlink) | **да**: без него `w:asciiTheme="minorHAnsi"` не разворачивается |
| `word/numbering.xml` | `abstractNum` (9 уровней: numFmt, lvlText, start, suff, pPr/rPr) + `num` (numId → abstractNumId, `lvlOverride`) | да, если нужны списки/автонумерация заголовков |
| `word/document.xml` | тело; `w:sectPr` (pgSz, pgMar, cols, docGrid, pgNumType — **по одной на секцию**), `w:pStyle`/`w:rStyle`, прямое форматирование | да: страница + статистика |
| `word/settings.xml` | `defaultTabStop`, `compat`, `themeFontLang`, `evenAndOddHeaders`, `trackChanges`, `documentProtection` | частично (предупреждения) |
| `word/fontTable.xml` | перечень шрифтов документа + `panose`, `charset`, `family` | опционально (подсказки для рендера) |
| `word/stylesWithEffects.xml` | копия стилей для Word 2010 (эффекты) | **нет**, но файл есть в Word-документах — нельзя случайно взять его вместо `styles.xml` |
| `word/header*.xml`, `footer*.xml`, `footnotes.xml`, `comments.xml` | колонтитулы, сноски, примечания — со своими `pStyle` | да, отдельные области |
| `word/vbaProject.bin` | макросы (`.docm`) | нет, но влияет на content-type → см. §5.1 |

---

## 4. Чек-лист извлекаемых параметров

Все значения ниже PoC уже вытаскивает и нормализует в СИ (pt/мм); в скобках — где лежит и в чём измеряется в XML.

**Страница и секции**
- формат/ориентация: `sectPr/pgSz @w @h @orient` (**dxa**, 1/1440″);
- поля: `pgMar @top @right @bottom @left @header @footer @gutter` (dxa);
- колонки `cols`, `docGrid` (тип сетки + `linePitch` — при `linePitch=381` Word «привязывает» строки к сетке, это влияет на фактический межстрочный);
- нумерация страниц: `pgNumType @fmt @start`, `titlePg`;
- **секций может быть несколько** (титул/приложения с другой ориентацией) — PoC берёт только body-level `sectPr`; в продукте нужно собирать все.

**Абзац** (`pPr`): `jc`, `ind` (`left/start`, `right/end`, `firstLine`, `hanging`; есть и *Chars-варианты в сотых долях знака*), `spacing` (`before/after` — twips или `*Lines` в сотых строки; `line` + `lineRule`: `auto` → 240 = одинарный, `exact`/`atLeast` → twips), `keepNext`, `keepLines`, `pageBreakBefore`, `widowControl`, `outlineLvl`, `numPr(numId, ilvl)`, `tabs`, `pBdr`, `shd`, `contextualSpacing`, `snapToGrid`.

**Прогон** (`rPr`): `rFonts` (ascii/hAnsi/eastAsia/cs + `*Theme`-ссылки + `hint`), `sz`/`szCs` (**полупункты**), `b`, `i`, `caps`, `smallCaps`, `strike`, `u@val/@color`, `color@val/@themeColor/@themeTint/@themeShade`, `highlight`, `vertAlign`, `spacing` (межбуквенный, twips), `kern`, `position`, `lang`, `vanish`, `noProof`.

**Таблицы**: `tblStyle` + стили типа `table` с `tblPr`/`tcPr` и **условными форматами** `tblStylePr @w:type` (`firstRow`, `band1Horz`, `lastColumn`, …) — без них шапка таблицы потеряет жирность/заливку.

**Нумерация**: уровни `abstractNum` (формат, шаблон текста `%1.%2`, суффикс, выравнивание, отступы уровня). Для ГОСТ это критично: «1.», «1.1», «а)», «—».

**Колонтитулы/сноски**: отдельные части со своими `pStyle` — для ГОСТ нужны нумерация внизу по центру и «Рисунок N — …» в подписях.

Соответствие типовым требованиям ГОСТ 7.32-2017 (для приёмки и для ГОСТ-пресета; значения сняты с шаблона `report-732-2017`): поля **30 / 15 / 20 / 20 мм**, Times New Roman **14 pt**, интервал **1.5**, абзацный отступ **12.5 мм**, выравнивание **по ширине**, подписи рисунков — по центру без отступа, таблицы — **12 pt**, нумерация страниц — внизу. Всё это извлекается (§7), т.е. ГОСТ-пресет можно *проверять* импортом реального шаблона, а не только декларировать.

---

## 5. Модель наследования и подводные камни (все проверены на файлах)

Порядок разрешения эффективных свойств:

```
docDefaults(rPrDefault/pPrDefault)
  → стиль: basedOn-цепочка (корень → лист), затем собственные pPr/rPr
    → link-пара (paragraph ↔ character: "Heading 1" ↔ "Heading 1 Char")
      → уровни нумерации (numPr → abstractNum/lvl → pPr/rPr)
        → прямое форматирование абзаца/прогона
```

### 5.1. Что реально ломает наивную реализацию

1. **`styleId` непрозрачен.** В ГОСТ-шаблоне: `Normal = a0`, `heading 1 = 1`, `List Paragraph = aff9` (155 абзацев!), `Заголовок графы = affa`. Матчить стили по `styleId` нельзя — только по `w:name` (+ встроенные id как подсказка). Наш PoC поэтому отдаёт `styleIndex {name → id}` и статистику использования в именах.
2. **Имена локализованы и кастомны.** `Раздел`, `Подраздел`, `Пункт`, `Название рисунка`, `Оглавление общий стиль`, `Боковик таблицы`. При этом встроенные остались английскими (`heading 1`). Нужны правила EN+RU и приоритет «используемый стиль важнее встроенного».
3. **`outlineLevel` — не семантический уровень.** В шаблоне `Заголовок структурного элемента` = 0, `Раздел` = 1, `Подраздел` = 2 (Word-семантика: 0 → «Уровень 1»). То есть «Раздел» формально второй уровень. Детекция заголовков по `outlineLvl` работает без словарей, но требует нормализации базы (PoC: `base = min(outlineLvl)` → `heading1..N` и предупреждение в `roleMapping.warnings`).
4. **Конфликт «явный шрифт vs шрифт темы».** `docDefaults` задаёт `w:asciiTheme="minorHAnsi"` (= Calibri), а `Normal` — явный `w:ascii="Times New Roman"`. По буквальному чтению ECMA-376 (CT_Fonts: «если `asciiTheme` опущен, используется `ascii`») приоритет у theme-атрибута, но Word/LibreOffice рендерят **Times New Roman** (проверено: `pdffonts` по PDF из шаблона — только TimesNewRomanPSMT, ни одного Calibri). PoC фиксирует политику `explicit-wins` и **явно возвращает конфликт** в `rPr.fontConflicts` — чтобы продукт мог показать это как предупреждение, а не молча угадать.
5. **Toggle-свойства.** `b`, `i`, `caps`, `smallCaps`, `strike`, `vanish` при наследовании работают как переключатели: если в дочернем стиле задано `w:b`, оно инвертирует унаследованное значение. Наивное «перезаписать сверху» даёт неверный результат в цепочках вида `Base(bold) → Derived(w:b)`.
6. **`numPr` с пустым `numId`.** В шаблоне `Подраздел` имеет `numPr{numId: null, ilvl: 1}` — нумерация приходит из `basedOn`/`numStyleLink`; отсутствие `numId` нельзя трактовать как «без списка».
7. **`latentStyles count="371"`.** Word декларирует 371 встроенный стиль, но в файле определены 64. Если показать пользователю «все стили Word», получим мусор из несуществующих стилей — брать только `w:style`.
8. **`stylesWithEffects.xml`** присутствует в Word-файлах и почти повторяет `styles.xml` — при альтернативном выборе части легко получить рассинхрон.
9. **Единицы.** Полупункты (`w:sz`), twips (dxa: интервалы, отступы, поля), 240-е доли строки (`w:line` при `lineRule=auto`), сотые доли знака (`*Chars`), восьмые пункта (`w:sz` границ), `w:pos` табов. Плюс четыре шрифтовых слота (`ascii`/`hAnsi`/`eastAsia`/`cs`) и `w:hint`.
10. **Прямое форматирование как основной источник.** ГОСТ-шаблон: 398 абзацев, `pStyle` у 310, `Normal` — 0 использований, 186 абзацев и 1199 прогонов с прямым форматированием (доля 0.516).

### 5.2. Форматы входа, которые нужно отсеивать/чинить до разбора (проверено)

- **`.doc` / зашифрованный / IRM**: это OLE/CFB, не zip — PoC детектит магию `D0 CF 11 E0` и отвечает понятной ошибкой (в API — 415 с текстом «нужна конвертация»).
- **`.docm`**: content-type `application/vnd.ms-word.document.macroEnabled.main+xml`; **python-docx 1.2.0 отказывается его открывать** (`ValueError: not a Word file`). Наш разбор по zip работает, но если команда возьмёт python-docx — нужен пре-конверт (`soffice --convert-to docx`, проверено: 64 → 72 стиля, ключевые параметры сохраняются).
- **ODT/RTF/PDF**: не OOXML; для ODT/RTF — `soffice --convert-to docx`; для PDF извлечение стилей надёжнее не делать (только как «угадывание» через конвертацию PDF→DOCX, отдельная задача, в ТЗ п.3 помечена как не приоритет).
- **Word 2003 XML** (`WordprocessingML`, другой namespace) — не поддерживаем, отвечаем 415.
- **Google Docs export**: `styleId` вида `kix.*`/нестандартные, тема может отсутствовать → тот же слой маппинга + предупреждение.

---

## 6. Подходы: сравнение

| Подход | Что даёт | Плюсы | Минусы / риски | Вердикт |
|---|---|---|---|---|
| **A. Прямой разбор OOXML** (PoC) | полная модель: стили, наследование, тема, нумерация, секции, статистика | нет зависимостей и лицензионных ограничений; работает на любом стеке; ~950 строк; 87 мс/1.1 МБ; контролируем каждое поле | наследование/токены/маппинг пишем сами; нужно покрыть редкие свойства | **основной** |
| **B. Библиотека-парсер** | python-docx, Apache POI (XWPF), docx4j, docx-rs (`docx-rust`), mammoth (docx→HTML) | быстрый старт, типизированная модель | python-docx не открывает `.docm` и не разрешает наследование (оба факта проверены); POI/docx4j тяжелы (JVM); в Go `unioffice` — AGPLv3/коммерция (для сетевого сервиса = раскрытие кода), `fumiama/go-docx` — AGPL-3.0, `nguyenthenguyen/docx` — MIT, но только замена текста (стили не читает); mammoth даёт HTML+`styleMap`, но не числа (мм/pt), нужные для ГОСТ | допустимо как **дополнение** (mammoth — для превью MD), не как ядро |
| **C. LibreOffice headless** | `--convert-to docx` (нормализация), `--convert-to fodt` (flat XML со стилями и `style:parent-style-name`), `--convert-to pdf` (рендер для валидации) | бесплатно, тянет `.doc`/`.docm`/ODT/RTF, разрешает наследование частично за нас; идеальный **оракул** для тестов | +1 тяжёлый сервис в кластере, 1–3 с на файл, версии LO влияют на результат; docx-экспорт **уплощает** оформление в прямое `rPr` (0.83 в контрольном файле) — как источник стилей не годится | **вспомогательный** (нормализация входа + тесты) |
| **D. Pandoc `reference.docx`** | шаблон оформления для генерации | привычно, минимум кода для выхода | для **извлечения** не работает: пересобирает документ по своим стилям (round-trip 38 → 70 стилей, `sectPr` в выходе нет), 22 % прямого форматирования; нестабильность уже зафиксирована в #11 | нет |
| **E. Коммерческие SDK** | Aspose.Words, GroupDocs, Adobe PDF Services | лучшая совместимость, поддержка PDF/защищённых файлов | платно, вендор-лок, противоречит «своя библиотека стилей» | не сейчас |

Итог: **A как ядро + C как нормализатор/оракул**, B — точечно (mammoth/POI при необходимости), D/E — нет.

---

## 7. Что показал PoC

`python3 docs/research/poc/docx_style_extract.py file.docx -o out.json` → нормализованный JSON (`schemaVersion: 0.1-poc`): `page`, `theme`, `docDefaults`, `styles[]`, `effectiveStyles{}`, `numbering`, `settings`, `document` (статистика), `dominantFormatting`, `roleMapping`, `coverage`.

### 7.1. Реальные файлы

| Файл | Стилей (p/ch/tbl/num) | Прямое форматирование | Доминирующее фактическое оформление | Маппинг ролей |
|---|---|---|---|---|
| ГОСТ-шаблон `report-732-2017.docm` (Word 16, 398 абзацев, 2285 прогонов) | 64 (39/22/2/1) | доля 0.516 (186 абзацев, 1199 прогонов) | TNR **14 pt** — 64.5 % прогонов обычным + 15.5 % жирным (заголовки); по ширине, отступ 12.5 мм, интервал 1.5 — 38.9 % абзацев | 25 ролей; покрыто **98 %** стилизованных абзацев (76 % всех) |
| `pandoc.docx` (15 абзацев) | 70 (32/37/1/0) | доля 0.22 (7 абзацев) | Cambria 12 pt — 65.7 % прогонов; Calibri 18 pt жирный — заголовки | 20 ролей, но покрыто только **40 %** абзацев: без роли остались `Compact` (7 абзацев), `Author`, `First Paragraph` |
| `test.docx` (Word 14) | 38 (25/11/1/1) | 0 | Calibri 16 pt / Cambria 12 pt | 11 ролей |

Выжимка по ГОСТ-шаблону (то, что пойдёт в тему):

```json
"page": {"page": {"widthMm": 210.01, "heightMm": 297.0},
         "margins": {"topMm": 20.0, "rightMm": 14.99, "bottomMm": 20.0, "leftMm": 30.0,
                     "headerMm": 12.49, "footerMm": 12.49}},
"effectiveStyles": {
  "a0": {"runProperties": {"font": {"ascii": "Times New Roman", "hAnsi": "Times New Roman",
                                   "asciiTheme": "minorHAnsi"},
                           "fontResolved": {"ascii": "Times New Roman", "hAnsi": "Times New Roman"},
                           "fontConflicts": [{"slot": "ascii", "explicit": "Times New Roman",
                                              "themeRef": "minorHAnsi", "themeValue": "Calibri",
                                              "policy": "explicit-wins"}],
                           "sizePt": 14.0},
         "paragraphProperties": {"spacing": {"afterPt": 0.0, "lineRule": "auto", "line": 1.5},
                                 "indent": {"firstLineMm": 12.51}, "alignment": "both"}}
}
```

Роли из ГОСТ-шаблона (фрагмент; `via` — как определено):

| Роль | Стиль | via | абзацев |
|---|---|---|---|
| `heading1` | Заголовок структурного элемента | outlineLevel(0) | 10 |
| `heading2` | Раздел | outlineLevel(1) | 7 |
| `heading3` | Подраздел | outlineLevel(2) | 27 |
| `heading4` | Пункт | outlineLevel(3) | 4 |
| `figureCaption` | Название рисунка | styleName | 19 |
| `tableCaption` | Название таблицы | styleName | 1 |
| `tableHeader` / `tableText` / `tableStub` | Заголовок графы / Текст таблицы / Боковик таблицы | styleName | 3 / 4 / 2 |
| `toc1..toc5` | toc 1 … toc 5 | styleName | 10 / 7 / 27 / 4 |
| `listItem` | List Paragraph | styleName | 155 |
| `equation` / `equationCaption` | Уравнение / Подпись уравнения | styleName | 1 / 3 |

### 7.2. Сверка с независимыми инструментами

- **python-docx** (после конвертации `.docm`→`.docx` через LO): `Normal` = Times New Roman 14 pt, `line_spacing` 1.5, `first_line_indent` 12.506 мм, поля 20.0 / 14.99 / 20.0 / 30.0 мм — **совпадает** с PoC. Но наследование python-docx не разрешает: у стиля `Раздел`, который наследует TNR 14 pt от `Normal`, `font.name` и `font.size` = `None`. Т.е. «эффективные» значения библиотека не даёт — их всё равно считать нам.
- **Рендер LibreOffice → PDF + `pdffonts`**: в PDF — `TimesNewRomanPSMT/Bold/Italic`, `LiberationSerif/Mono`, `DejaVuSerif-Italic`, `OpenSymbol`; **ни одного Calibri**. Это подтверждает политику `explicit-wins` (Calibri из темы не используется).
- **Pandoc round-trip** (`pandoc test.docx -o test_rt.docx`): стилей 38 → 70 (свои), пересечение имён — 6 служебных, `page: {}` — геометрия страницы потеряна полностью. Для извлечения стилей pandoc непригоден.
- **PoC как оракул для LO-конвертации**: у `.docm` и его `.docx`-копии совпадают ключевые параметры (стилей 64 → 72, добавлены LO-специфичные).
- **Проверка устойчивости:** не-zip вход → понятная ошибка; OLE-магия → отдельное сообщение; циклический `basedOn` (`Normal → Default Paragraph Font → Normal`) → рекурсия останавливается, стилей 64; отсутствие `numbering.xml` → пустая секция вместо падения; `pPr/suppressAutoHyphens` — единственный необработанный элемент, попал в `coverage.unsupportedElements`.
- **Производительность (медиана 5 прогонов, включая старт интерпретатора):** ГОСТ-шаблон 1.1 МБ → 87 мс; `pandoc.docx` → 44 мс; `test.docx` → 42 мс.

### 7.3. Чего PoC сознательно не делает

секции кроме body-level `sectPr`; колонтитулы/сноски как отдельные области (стили в них есть, но не собираются); условные форматы таблиц в применении (только извлекаются, не применяются); поля, TOC и `fldSimple` как структура; `w:altChunk`; отслеживаемые изменения; эффекты (тени/контуры). Всё, что встречается в `rPr`/`pPr`/`w:style` и не описано, попадает в `coverage.unsupportedElements` — молча ничего не теряется.

---

## 8. Контракт данных: маппинг на `db.sql`

Схема уже подходит, менять её не нужно:

- `themes.parameters` (jsonb) ← «оформление» документа: `page`, `docDefaults`, `theme.fonts`, `numbering` (пресеты), `roles` (роль → параметры), `provenance` (файл, sha256, версия схемы, доля прямого форматирования).
- `styles(type='render', data jsonb)` ← одна запись с нормализованными свойствами ролей для рендерера.
- `styles(type='transform', data jsonb)` ← карта «имя стиля в документе → роль» + допуски для валидации (`±10 %` по отступу и т.п.), чтобы US-06 работал.
- `theme_collections` — импортированный стиль логично класть в личную коллекцию автора (`user_theme_collections.role='owner'`).

Предлагаемый контракт ответа API (сокращённо; `schemaVersion` — для миграций):

```json
{
  "schemaVersion": "1.0",
  "source": {"sha256": "…", "generator": "Microsoft Office Word 16.0000", "sections": 2},
  "theme": {
    "page": {"format": "A4", "marginsMm": {"top": 20, "right": 15, "bottom": 20, "left": 30}},
    "defaults": {"fontFamily": "Times New Roman", "sizePt": 14,
                 "lineSpacing": 1.5, "firstLineMm": 12.5, "alignment": "both"},
    "colors": {"accent1": "5B9BD5"}
  },
  "roles": {
    "heading2": {"sourceStyleId": "ae", "sourceStyleName": "Раздел", "confidence": 0.9,
                 "via": "outlineLevel", "usedParagraphs": 7,
                 "fontFamily": "Times New Roman", "sizePt": 14, "bold": true,
                 "alignment": "left", "spaceBeforePt": 12, "spaceAfterPt": 6, "keepNext": true},
    "figureCaption": {"sourceStyleName": "Название рисунка", "alignment": "center",
                      "firstLineMm": 0, "sizePt": 14}
  },
  "warnings": [
    {"code": "THEME_FONT_CONFLICT", "slot": "ascii", "explicit": "Times New Roman",
     "themeValue": "Calibri", "policy": "explicit-wins"},
    {"code": "DIRECT_FORMATTING_DOMINANT", "share": 0.516},
    {"code": "UNMAPPED_STYLES", "styles": ["Список исполнителей", "Заголовки основной части"]}
  ],
  "coverage": {"styleCoverage": 0.98, "bodyFromDominantFormatting": true}
}
```

Интеграция в пайплайн (уже есть в диаграмме — `job_request`, статусы `QUEUED → PARSING → …`):
1. `POST /v1/themes/extract` (multipart, лимит 10 МБ по ТЗ) → `job_request{type='extraction'}` → 202 + `external_id`;
2. воркер: sha256 → кэш (`media` + `file_hash`) → нормализация при необходимости (LO) → разбор → маппинг ролей;
3. ответ: `theme` + `warnings` + `roleMapping` (для экрана подтверждения), сохранение в `themes/styles` только после подтверждения пользователем;
4. ошибки: 415 `UNSUPPORTED_FORMAT` (`.doc`, ODT, PDF, Word2003XML), 422 `NO_STYLES` (нет `styles.xml` — битый файл), 413 `TOO_LARGE`, 409 при дубликате sha (отдаём существующую тему).

---

## 9. Валидация и тесты (что закладывать сразу)

1. **Golden-файлы**: 8–12 docx в репозитории (Word 2016/365, Mac Word, LibreOffice, Google Docs export, ГОСТ-шаблон, «грязный» файл без стилей, файл с таблицами и условными форматами, `.docm`, битый zip) + ожидаемый JSON с допуском (`±0.01 мм`, `±0.1 pt`).
2. **Метрика покрытия**: `styleCoverage` = доля абзацев, чьи стили смаппились в роли (PoC-порог для ГОСТ-шаблона — 0.98); падение метрики = регресс правил маппинга.
3. **Round-trip через LibreOffice**: тема → `reference.docx` → наполнить тестовым контентом → PDF → сравнить с PDF исходного шаблона по инвариантам: список шрифтов (`pdffonts`), поля (bbox первой страницы), межстрочный (по координатам базовых линий), размер кегля. Это единственный способ поймать «тихие» ошибки единиц измерения.
4. **Property/fuzz-тесты парсера**: битые XML, гигантские `styles.xml`, zip-бомба (лимит на unpacked size и ratio), XXE/billion-laughs (в Python — `defusedxml`, в Go `encoding/xml` сущности не разворачивает), глубина наследования > 32, циклы `basedOn`.
5. **Снапшоты поддерживаемых элементов**: `coverage.unsupportedElements` в CI — если в новом образце появился необработанный элемент, тест падает и требует осознанного решения (а не молча теряет оформление).

---

## 10. Риски

| Риск | Влияние | Мера |
|---|---|---|
| Извлекаем «стили», а документ оформлен руками (наш кейс: 52 % прямого форматирования) | импортированный стиль не соответствует ожиданию пользователя | `dominantFormatting` + предупреждение + экран подтверждения |
| Неточная семантика ролей (outlineLevel ≠ уровень, локализованные имена) | заголовки/подписи едут не туда | `roleMapping` с `via`/`alternatives`/`warnings`, обязательное подтверждение |
| Конфликт theme vs explicit | неверный шрифт в теме | фиксированная политика + `fontConflicts` в ответе + тест на PDF-рендере |
| Зависимость от версии LibreOffice (если брать её как нормализатор) | разное поведение в CI и проде | пиннинг образа LO, контрактные тесты на PDF-инвариантах |
| Недоверенный ввод (zip-бомбы, XXE, гигантские XML) | DoS воркера | лимиты размера/ratio, defusedxml, таймауты, отдельная очередь |
| Юридические ограничения библиотек | блокировка релиза | не тащить AGPL (`unioffice`, `fumiama/go-docx`) в сетевой сервис |
| Расхождение модели темы и рендерера | стиль «не воспроизводится» | один JSON-контракт, версионирование `schemaVersion`, golden-тесты рендера |

---

## 11. План работ (черновик, для оценки)

| Этап | Содержание | Выход |
|---|---|---|
| 1. Ядро (3–4 дня) | перенос PoC в код сервиса: разбор `styles/theme/numbering/sectPr` (все секции), эффективные стили, toggle-свойства, `link`-пары | библиотека `styles-extractor` + golden-тесты |
| 2. Фактическое оформление (2 дня) | `dominantFormatting`, кластеризация абзацев/прогонов, определение «тела» документа | поля `body` + предупреждения |
| 3. Маппинг ролей (2–3 дня) | правила EN/RU + встроенные id + `outlineLevel`, `alternatives`, `confidence`; ГОСТ-пресет | `roleMapping` + метрика покрытия в CI |
| 4. Контракт и API (2 дня) | JSON-схема `1.0`, эндпоинт извлечения, коды ошибок, кэш по sha256, запись в `themes/styles` после подтверждения | OpenAPI + миграция (если нужна) |
| 5. Нормализация входа (1–2 дня) | детект формата, `.doc/.docm/ODT/RTF` → LO-конвертация, лимиты, безопасность | воркер нормализации |
| 6. Валидация (2 дня) | PDF-инварианты через LO, fuzz, набор образцов | CI-джоба `styles-conformance` |

Итого ~12–15 человеко-дней до продакшн-качества; этапы 1–3 дают демо «загрузил ГОСТ-шаблон → получил тему».

---

## 12. Открытые вопросы к команде

1. Язык бэкенда (issue #9 ещё открыт): если Go — разбор на `archive/zip` + `encoding/xml` переносится 1:1; если Python — `defusedxml`/`lxml`. От этого зависит только обвязка, модель одна.
2. Нужен ли импорт `.doc`/ODT в MVP — это решает, поднимаем ли LibreOffice-сервис сразу (влияет на инфраструктуру: +1 под).
3. Кто владеет экраном «подтверждение маппинга стилей» (issue #12, прототип UI) — формат `roleMapping` должен быть согласован с ним.
4. Где хранить исходный `.docx` после извлечения: `media` в SeaweedFS с TTL по 152-ФЗ (US-12) или удалять сразу после разбора (в PoC не храним ничего, только sha256).
5. Нужен ли экспорт темы в `reference.docx`/`.dotx` (US-13) в той же итерации — иначе импорт будет «односторонним».

---

## Приложение A. Файлы и воспроизведение

```
docs/research/docx-style-extraction.md   — этот отчёт
docs/research/poc/docx_style_extract.py  — PoC-экстрактор (stdlib, CLI)
```

```bash
# извлечь стили
python3 docs/research/poc/docx_style_extract.py template.docx -o theme.json
# без вычисления эффективных стилей (быстрее, меньше JSON)
python3 docs/research/poc/docx_style_extract.py template.docx --no-effective

# нормализация «грязного» входа и оракул для тестов
soffice --headless --convert-to docx --outdir out input.docm
soffice --headless --convert-to pdf  --outdir out input.docx && pdffonts out/input.pdf
# плоский XML со стилями (альтернативный способ посмотреть разрешённые стили)
soffice --headless --convert-to fodt --outdir out input.docx
```

Образцы, на которых проверялось: `report-732-2017` (ГОСТ-шаблон с макросами, Microsoft Word 16), `pandoc.docx` (pandoc 3.1.11.1 из markdown с заголовками/списками/таблицей), `test.docx` (Mac Word 14), плюс синтетические: OLE-файл, не-zip, `basedOn`-цикл, отсутствующий `numbering.xml`.

## Приложение B. Источники

- ECMA-376 / ISO 29500, части 1 (WordprocessingML): `CT_Fonts` §17.3.2.26, `rPr` §17.3.2, `pPr` §17.3.1, наследование стилей §17.7.2.
- [Шаблон отчёта по ГОСТ 7.32-2017 с макросами](https://github.com/konstantin-morenko/report-732-2017) — использован как реальный образец ГОСТ-оформления.
- [mammoth.js — style map](https://github.com/mwilliamson/mammoth.js/blob/master/README.md) — подход «docx → семантические роли» (совпадает с нашим `roleMapping`, но без числовых параметров).
- [unioffice (AGPLv3/коммерция)](https://github.com/IGLOU-EU/unioffice), [fumiama/go-docx (AGPL-3.0)](https://github.com/fumiama/go-docx), [docx-rs / docx-rust](https://docs.rs/docx-rs/latest/docx_rs/) — оценка Go/Rust-библиотек.
- python-docx 1.2.0, LibreOffice 25.2.3.2, pandoc 3.1.11.1 — поведение фиксировалось экспериментально (см. §7.2).
- [ГОСТ-оформление в Word: шаблоны и стили](https://ivankornev.com/ru/articles/home-tech/setup/gost-formatting-word-templates-styles/) — типовой набор ГОСТ-параметров для сверки пресета.
