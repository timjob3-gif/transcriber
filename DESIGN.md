# Design System — Транскрибатор

Справочник токенов и правил. Добавляя UI-элемент — сверяйся здесь.

---

## Цвета (CSS vars)

| Токен       | Значение    | Назначение                              |
|-------------|-------------|-----------------------------------------|
| `--bg`      | `#0e0e0e`   | Фон страницы                            |
| `--surface` | `#1a1a1a`   | Карточки, модалки, панели               |
| `--border`  | `#2a2a2a`   | Границы элементов                       |
| `--accent`  | `#7c6af7`   | Акцент: кнопки, прогресс-бар, фокус     |
| `--text`    | `#e8e8e8`   | Основной текст                          |
| `--muted`   | `#666`      | Вторичный текст, подписи                |
| `--success` | `#4ade80`   | Успех, GPU CUDA, готово                 |
| `--error`   | `#f87171`   | Ошибки                                  |
| `--radius`  | `10px`      | Радиус карточек и основных блоков       |

### Цвета спикеров (JS-массив `_SPEAKER_COLORS`)

| Индекс | Background                    | Text color  |
|--------|-------------------------------|-------------|
| S0     | `rgba(124,106,247,0.18)`      | `#a99fff`   |
| S1     | `rgba(74,222,128,0.15)`       | `#4ade80`   |
| S2     | `rgba(251,146,60,0.18)`       | `#fb923c`   |
| S3     | `rgba(244,114,182,0.18)`      | `#f472b6`   |
| S4     | `rgba(250,204,21,0.18)`       | `#facc15`   |
| S5     | `rgba(56,189,248,0.18)`       | `#38bdf8`   |

---

## Типографика

| Роль             | Font                              | Size  | Weight |
|------------------|-----------------------------------|-------|--------|
| Основной текст   | `'Segoe UI', system-ui, sans-serif` | 14px  | 400    |
| Заголовки модалок| inherit                           | 14px  | 600    |
| Имя задачи       | inherit                           | 13px  | 400    |
| Подписи/метки    | inherit                           | 11–12px | 400  |
| Таймкоды         | `'Consolas', monospace`           | 11px  | 400    |
| Спикер-бейджи    | `'Consolas', monospace`           | 10px  | 600    |

---

## Spacing

| Контекст              | Значение |
|-----------------------|----------|
| Padding карточки      | `12px 14px` |
| Gap между карточками  | `8px`    |
| Padding main          | `20px`   |
| Gap внутри карточки   | `7px`    |
| Padding header        | `14px 20px` |
| Padding settings-body | `16px`   |
| Gap settings rows     | `14px`   |

---

## Границы и радиусы

| Элемент              | Радиус  |
|----------------------|---------|
| Карточки, main блоки | `10px` (`--radius`) |
| Кнопки               | `6px`   |
| Модальные окна       | `12px`  |
| Welcome box          | `16px`  |
| Спикер-бейджи        | `10px`  |
| Прогресс-бар         | `2px`   |

---

## Компоненты

### Кнопки `.btn`

- Primary: `background: var(--accent)`, белый текст, `border-radius: 6px`
- Ghost: `background: var(--surface)`, `border: 1px solid var(--border)`
- Small: `padding: 4px 10px`, `font-size: 12px`
- Hover: `opacity: 0.85`; Active: `opacity: 0.7`

### Job card `.job`

Статусы: `pending` / `running` / `done` / `error`
- Progress bar: 3px высота, `var(--accent)` цвет, shimmer-анимация при `running`
- Stage indicators: `⏳ Загружается модель…` / `🎤 Определяю спикеров…`
- Skeleton: 3 строки при `running` без сегментов
- Result block: зелёный фон `rgba(74,222,128,0.07)` при `done`

### Settings modal

Ширина: `380px`. Три группы с разделителями `.settings-group-label`:
1. **Транскрипция** — модель, язык
2. **Вывод** — папка
3. **Голоса** — чекбокс диаризации, select количества участников

### Viewer panel

Правая панель, ширина `400px`, `slideInRight 0.22s`.
Кнопки: `📋 С таймкодами` (копирует `[MM:SS] [SN] текст`), `✕` закрыть.

---

## Layout

- `body`: flex column, `100vh`, `overflow: hidden`
- `main`: `max-width: 860px`, `width: 100%`, `align-self: center`
- `header`: full width, `flex-shrink: 0`
- `#queue`: `flex: 1`, `overflow-y: auto`

---

## Анимации

| Имя               | Назначение                      |
|-------------------|---------------------------------|
| `slideIn`         | Появление карточки              |
| `flashGreen`      | Успешное завершение             |
| `shake`           | Ошибка                          |
| `pulseBorder`     | Drag-over drop zone             |
| `progress-shimmer`| Shimmer на прогресс-баре        |
| `skeleton-shimmer`| Skeleton loader                 |
| `pulse-muted`     | Stage-индикаторы (загрузка/диар)|
| `slideInRight`    | Появление viewer panel          |
