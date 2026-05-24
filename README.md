# translator-bot

Telegram-бот переводчик. Принимает текст на любом языке, переводит на выбранный пользователем язык через LLM (OpenRouter с fallback по 4 моделям) и по кнопке озвучивает результат через Edge TTS.

## Возможности

- 8 языков: 🇷🇺 русский, 🇬🇧 английский, 🇪🇸 испанский, 🇫🇷 французский, 🇩🇪 немецкий, 🇮🇹 итальянский, 🇨🇳 китайский, 🇸🇦 арабский
- Выбор языка через постоянную клавиатуру с флагами
- Fallback по моделям: 2 бесплатные → 2 платные, если предыдущая зафейлилась/рейт-лимит
- Озвучка перевода через Microsoft Edge TTS (нативные голоса для каждого языка)
- Персистентность: язык пользователя и кэш TTS хранятся в SQLite (переживают перезапуск)
- Таймаут 30с на запрос к LLM, чтобы зависший провайдер не блокировал бота

## Стек

- Python 3.11+
- `python-telegram-bot` 21.6
- `openai` SDK (`AsyncOpenAI`) → OpenRouter
- `aiosqlite` для хранения состояния
- `edge-tts` для синтеза речи
- Деплой: Fly.io (регион Frankfurt)

## Модели OpenRouter (порядок fallback)

1. `venice/uncensored:free` — FREE
2. `nousresearch/hermes-3-llama-3.1-405b:free` — FREE
3. `thedrummer/cydonia-24b-v2` — PAID
4. `sao10k/l3-euryale-70b` — PAID

## Запуск локально

```bash
pip install -r requirements.txt
cp .env.example .env   # вписать TELEGRAM_TOKEN и OPENROUTER_API_KEY
python bot.py
```

## Деплой на Fly.io

```bash
fly launch          # один раз — создать приложение
fly secrets set TELEGRAM_TOKEN=... OPENROUTER_API_KEY=...
fly deploy
```

## Структура

- `bot.py` — весь бот в одном файле
- `bot.db` — SQLite (создаётся автоматически при первом запуске)
- `Dockerfile` + `fly.toml` — конфиг деплоя
- `.env.example` — шаблон для локальных переменных окружения
