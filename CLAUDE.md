# trans-bot

Telegram-бот переводчик. Принимает текст, переводит через OpenRouter (LLM с fallback по 4 моделям), озвучивает через Edge TTS.

## Стек
- python-telegram-bot 21.6 (не aiogram — проект начат на PTB, не менять без причины)
- openai SDK → AsyncOpenAI → OpenRouter
- aiosqlite — хранение user_lang и tts_cache
- edge-tts — синтез речи
- Деплой: Fly.io, Frankfurt region

## Структура
- `bot.py` — весь бот в одном файле
- `bot.db` — SQLite (создаётся автоматически при старте, не коммитить)
- `.env` — TELEGRAM_TOKEN, OPENROUTER_API_KEY (не коммитить)
- `Dockerfile` + `fly.toml` — деплой

## Запуск локально
```
pip install -r requirements.txt
cp .env.example .env   # заполни токены
python bot.py
```

## Деплой на Fly.io
```
fly deploy
fly secrets set TELEGRAM_TOKEN=... OPENROUTER_API_KEY=...
```

## Модели OpenRouter (порядок fallback)
1. venice/uncensored:free (FREE)
2. nousresearch/hermes-3-llama-3.1-405b:free (FREE)
3. thedrummer/cydonia-24b-v2 (PAID)
4. sao10k/l3-euryale-70b (PAID)
