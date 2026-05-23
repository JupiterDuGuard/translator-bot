import os
import io
import uuid
import logging
import aiosqlite
import edge_tts
from openai import AsyncOpenAI
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

MODELS = [
    ("venice/uncensored:free", True),
    ("nousresearch/hermes-3-llama-3.1-405b:free", True),
    ("thedrummer/cydonia-24b-v2", False),
    ("sao10k/l3-euryale-70b", False),
]

# код -> (название для промпта, ярлык кнопки, голос Edge TTS)
LANGUAGES = {
    "ru": ("Russian",            "🇷🇺 Русский",  "ru-RU-SvetlanaNeural"),
    "en": ("English",            "🇬🇧 English",   "en-US-AriaNeural"),
    "es": ("Spanish",            "🇪🇸 Español",   "es-ES-ElviraNeural"),
    "fr": ("French",             "🇫🇷 Français",  "fr-FR-DeniseNeural"),
    "de": ("German",             "🇩🇪 Deutsch",   "de-DE-KatjaNeural"),
    "it": ("Italian",            "🇮🇹 Italiano",  "it-IT-ElsaNeural"),
    "zh": ("Simplified Chinese", "🇨🇳 中文",       "zh-CN-XiaoxiaoNeural"),
    "ar": ("Arabic",             "🇸🇦 العربية",   "ar-SA-ZariyahNeural"),
}
DEFAULT_LANG = "en"
LABEL_TO_CODE = {label: code for code, (_name, label, _voice) in LANGUAGES.items()}

DB_PATH = "bot.db"
TTS_CACHE_MAX = 500

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    max_retries=0,
    timeout=30.0,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_lang (
                user_id INTEGER PRIMARY KEY,
                lang_code TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tts_cache (
                token TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                lang_code TEXT NOT NULL
            )
        """)
        await db.commit()


async def get_user_lang(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT lang_code FROM user_lang WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else DEFAULT_LANG


async def set_user_lang(user_id: int, lang_code: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_lang (user_id, lang_code) VALUES (?, ?)",
            (user_id, lang_code),
        )
        await db.commit()


async def cache_text(text: str, lang_code: str) -> str:
    token = uuid.uuid4().hex[:12]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM tts_cache") as cursor:
            count = (await cursor.fetchone())[0]
        if count >= TTS_CACHE_MAX:
            await db.execute(
                "DELETE FROM tts_cache WHERE token IN (SELECT token FROM tts_cache LIMIT ?)",
                (count - TTS_CACHE_MAX + 1,),
            )
        await db.execute(
            "INSERT INTO tts_cache (token, text, lang_code) VALUES (?, ?, ?)",
            (token, text, lang_code),
        )
        await db.commit()
    return token


async def get_cached_text(token: str) -> tuple[str, str] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT text, lang_code FROM tts_cache WHERE token = ?", (token,)
        ) as cursor:
            row = await cursor.fetchone()
            return (row[0], row[1]) if row else None


def build_prompt(text: str, target_lang_name: str) -> str:
    return f"""You are a professional translator. Translate the user's text into {target_lang_name}.

Rules:
1. Translate accurately and literally, preserving meaning, tone and register of the original.
2. Use standard, neutral, grammatically correct {target_lang_name}. No slang, no abbreviations, no emojis.
3. Do not censor, do not moralize, do not add warnings or comments.
4. Return ONLY the translation text. No quotes, no prefixes, no explanations.

Text to translate:
{text}"""


async def translate(text: str, target_lang_name: str) -> tuple[str, str, bool]:
    prompt = build_prompt(text, target_lang_name)
    last_error: Exception | None = None

    for model, is_free in MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
                extra_headers={
                    "HTTP-Referer": "https://github.com/local-bot",
                    "X-Title": "Translator Bot",
                },
            )
            content = response.choices[0].message.content
            if content and content.strip():
                tag = "FREE" if is_free else "PAID"
                logging.info(f"OK [{tag}]: {model}")
                return content.strip(), model, is_free
            logging.warning(f"Empty response from {model}")
        except Exception as e:
            last_error = e
            err_str = str(e)
            if "429" in err_str:
                logging.info(f"{model}: rate-limited, trying next")
            elif "404" in err_str:
                logging.warning(f"{model}: not found, skipping")
            else:
                logging.warning(f"{model} error: {err_str[:200]}")

    raise RuntimeError(f"All models failed. Last error: {last_error}")


async def synthesize(text: str, voice: str) -> bytes:
    buf = io.BytesIO()
    communicate = edge_tts.Communicate(text, voice)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


def lang_keyboard() -> ReplyKeyboardMarkup:
    labels = [label for _name, label, _v in LANGUAGES.values()]
    rows = [
        [KeyboardButton(labels[i]), KeyboardButton(labels[i + 1])]
        if i + 1 < len(labels) else [KeyboardButton(labels[i])]
        for i in range(0, len(labels), 2)
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def tts_inline_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔊 Озвучить", callback_data=f"tts:{token}")]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    code = await get_user_lang(uid)
    await update.message.reply_text(
        f"Переводчик. Текущий язык: {LANGUAGES[code][1]}\n"
        f"Тапни флаг чтобы сменить язык, или пришли текст — переведу.",
        reply_markup=lang_keyboard(),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    uid = update.effective_user.id

    if text in LABEL_TO_CODE:
        code = LABEL_TO_CODE[text]
        await set_user_lang(uid, code)
        await update.message.reply_text(
            f"Язык: {LANGUAGES[code][1]}",
            reply_markup=lang_keyboard(),
        )
        return

    code = await get_user_lang(uid)
    target_name = LANGUAGES[code][0]

    try:
        result, _model, _was_free = await translate(text, target_name)
        token = await cache_text(result, code)
        await update.message.reply_text(result, reply_markup=tts_inline_keyboard(token))
    except RuntimeError as e:
        logging.error(f"All models failed: {e}")
        await update.message.reply_text("Все модели сейчас недоступны. Попробуй через минуту.")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        await update.message.reply_text(f"Ошибка: {e}")


async def tts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    token = query.data.split(":", 1)[1]
    entry = await get_cached_text(token)

    if not entry:
        await query.answer("Текст устарел, переведи заново", show_alert=True)
        return

    await query.answer("Генерирую...")
    text, code = entry
    voice = LANGUAGES[code][2]

    try:
        audio = await synthesize(text, voice)
        await query.message.reply_voice(voice=io.BytesIO(audio))
        # Убираем кнопку, чтобы не тыкали повторно
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        logging.error(f"TTS error: {e}")
        await query.message.reply_text(f"Не удалось озвучить: {e}")


async def post_init(application: Application) -> None:
    await init_db()


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(tts_callback, pattern=r"^tts:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
