import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import google.generativeai as genai
from PIL import Image
import io
import time
import threading
import requests
import logging
from flask import Flask

# --- 1. СИСТЕМА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# ---------------------------------------------

# --- НАСТРОЙКИ ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

IMAGE_GEN_MODEL_NAME = 'gemini-2.0-flash-exp-image-generation' 
VISION_MODEL_NAME = 'gemini-2.5-flash' 
# ----------------------------------------------------------------

# Проверка и настройка API
if not TELEGRAM_BOT_TOKEN or not GOOGLE_API_KEY:
    logger.critical("!!! КРИТИЧЕСКАЯ ОШИБКА: Не найдены ключи API!")
    exit()
try:
    genai.configure(api_key=GOOGLE_API_KEY)
    image_gen_model = genai.GenerativeModel(IMAGE_GEN_MODEL_NAME) 
    vision_model = genai.GenerativeModel(VISION_MODEL_NAME)
    logger.info("Все модели успешно инициализированы.")
except Exception as e:
    logger.critical(f"!!! Не удалось инициализировать модели Gemini: {e}")
    exit()

# --- СИСТЕМА "АНТИ-СОН" ---
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is alive and running!"
@app.route('/ping')
def ping(): return "pong", 200
def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    from waitress import serve
    serve(app, host='0.0.0.0', port=port)
def keep_awake():
    render_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}" if os.environ.get('RENDER_EXTERNAL_HOSTNAME') else None
    if not render_url:
        logger.warning("!!! Не удалось определить URL для анти-сна.")
        return
    while True:
        try: requests.get(f"{render_url}/ping", timeout=10)
        except: pass
        time.sleep(240)
# -----------------------------------------------------------

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
user_chats = {}

# --- Меню и Вспомогательные функции ---
def create_main_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton('🖼️ Создать промпт'), KeyboardButton('🔎 Детальный анализ'))
    markup.add(KeyboardButton('🔤 Перевести текст с фото'))
    markup.add(KeyboardButton('🗑️ Очистить память'), KeyboardButton('📊 Статус'), KeyboardButton('ℹ️ Помощь'))
    return markup

def send_generated_image(chat_id, response, caption, original_message):
    try:
        if response and response.parts:
            image_part = next((part for part in response.parts if part.mime_type.startswith("image/")), None)
            if image_part:
                bot.send_photo(chat_id, image_part.blob.data, caption=caption)
                return
        bot.reply_to(original_message, "Не удалось сгенерировать изображение. Возможно, сработал фильтр безопасности.")
    except Exception as e:
        logger.error(f"Критическая ошибка в send_generated_image: {e}")
        bot.reply_to(original_message, "Произошла серьезная внутренняя ошибка при отправке изображения.")

# --- КОМАНДЫ БОТА И ОБРАБОТЧИКИ КНОПОК ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я многофункциональный AI-бот. Используйте меню для навигации.", reply_markup=create_main_menu())

@bot.message_handler(func=lambda message: message.text == 'ℹ️ Помощь')
def handle_help(message):
    help_text = (
        "**Инструкция по работе с ботом:**\n\n"
        "1. **Выбери действие:** Нажми одну из кнопок в меню.\n"
        "2. **Следуй инструкции:** Бот попросит отправить фото или текст.\n"
        "3. **Получи результат!**\n\n"
        "**Описание функций:**\n"
        "🖼️ **Создать промпт** — Отправь фото, чтобы получить короткий список тегов на английском для генерации похожих изображений.\n\n"
        "🔎 **Детальный анализ** — Отправь любое фото для получения подробного структурированного отчета о том, что на нем изображено.\n\n"
        "🔤 **Перевести текст** — Отправь фото с текстом на любом языке, чтобы получить его перевод на русский.\n\n"
        "🗑️ **Очистить память** — Сбрасывает историю диалога со мной.\n\n"
        "📊 **Статус** — Показывает техническую информацию о боте.\n\n"
        "✍️ **Диалог и рисование** — Просто напиши мне сообщение для общения или используй команду 'Нарисуй...', чтобы я создал изображение."
    )
    bot.reply_to(message, help_text, parse_mode="Markdown", reply_markup=create_main_menu())

@bot.message_handler(func=lambda message: message.text == '📊 Статус')
def handle_status(message):
    status_text = (
        f"**📊 Статус системы:**\n\n"
        f"• **Память вашего чата:** {'✅ Активна' if message.chat.id in user_chats else '💤 Очищена'}\n"
        f"• **Активных диалогов:** {len(user_chats)}\n\n"
        f"**🧠 Используемые модели:**\n"
        f"• **Диалог/Анализ:** `{VISION_MODEL_NAME}`\n"
        f"• **Генерация:** `{IMAGE_GEN_MODEL_NAME}`"
    )
    bot.reply_to(message, status_text, parse_mode="Markdown", reply_markup=create_main_menu())

@bot.message_handler(func=lambda message: message.text == '🗑️ Очистить память')
def reset_memory(message):
    if message.chat.id in user_chats:
        del user_chats[message.chat.id]
    bot.reply_to(message, "Память диалога очищена.", reply_markup=create_main_menu())

# --- РЕГИСТРАЦИЯ СЛЕДУЮЩИХ ШАГОВ ---

@bot.message_handler(func=lambda message: message.text == '🖼️ Создать промпт')
def request_prompt_photo(message):
    msg = bot.reply_to(message, "Отправь фото, чтобы получить готовый промпт.")
    bot.register_next_step_handler(msg, process_prompt_photo)

@bot.message_handler(func=lambda message: message.text == '🔎 Детальный анализ')
def request_analysis_photo(message):
    msg = bot.reply_to(message, "Отправь фото для детального анализа.")
    bot.register_next_step_handler(msg, process_analysis_photo)

@bot.message_handler(func=lambda message: message.text == '🔤 Перевести текст с фото')
def request_translation_photo(message):
    msg = bot.reply_to(message, "Отправь фото с текстом для перевода.")
    bot.register_next_step_handler(msg, process_translation_photo)

# --- СПЕЦИАЛИЗИРОВАННЫЕ ОБРАБОТЧИКИ ФОТО ---

def process_photo_task(message, instruction, task_name):
    """Универсальная функция для обработки фото с помощью двухшагового метода."""
    if not message.photo:
        bot.reply_to(message, "Пожалуйста, отправь фото.")
        return
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        file_id = message.photo[-1].file_id
        downloaded_file = bot.download_file(bot.get_file(file_id).file_path)
        image = Image.open(io.BytesIO(downloaded_file))
        
        chat_session = vision_model.start_chat()
        chat_session.send_message(["Проанализируй это изображение.", image]) # Шаг 1
        response = chat_session.send_message(instruction) # Шаг 2

        if task_name == "prompt":
            clean_text = response.text.replace("\n", ", ").replace("*", "").strip()
            bot.reply_to(message, f"Готовый промпт:\n\n`{clean_text}`", parse_mode="Markdown")
        else:
            bot.reply_to(message, response.text, parse_mode="Markdown" if task_name == "analysis" else None)

    except Exception as e:
        logger.error(f"Ошибка в {task_name}: {e}")
        bot.reply_to(message, "Не удалось обработать изображение. Возможно, ответ был заблокирован фильтром безопасности.")

def process_prompt_photo(message):
    instruction = "АНАЛИЗ ИЗОБРАЖЕНИЯ ДЛЯ ПРОМПТА. ВЫВОД: ТОЛЬКО АНГЛИЙСКИЙ ЯЗЫК, КЛЮЧЕВЫЕ СЛОВА, ЧЕРЕЗ ЗАПЯТУЮ. БЕЗ ОБЪЯСНЕНИЙ. НАЧАТЬ С 'masterpiece, best quality'."
    process_photo_task(message, instruction, "prompt")

def process_analysis_photo(message):
    instruction = "Твоя роль: высокоточный мультидисциплинарный аналитик. Проведи исчерпывающий и объективный анализ изображения на русском языке. Структура отчета: 1. **Общая сводка**, 2. **Ключевые объекты**, 3. **Окружение и фон**, 4. **Детали и надписи**, 5. **Предположительный контекст**."
    process_photo_task(message, instruction, "analysis")

def process_translation_photo(message):
    instruction = "Извлеки весь текст с изображения и дословно переведи его на русский. Твой ответ должен содержать ТОЛЬКО переведенный текст. Если текста нет, напиши 'Текст не найден'."
    process_photo_task(message, instruction, "translation")

# --- ОБЩИЕ ОБРАБОТЧИКИ ---

@bot.message_handler(content_types=['photo'])
def handle_default_photo(message):
    """Обрабатывает фото, отправленные без предварительной команды."""
    caption = message.caption if message.caption else ""
    redraw_keywords = ['перерисуй', 'в стиле', 'сделай как']
    
    if any(keyword in caption.lower() for keyword in redraw_keywords):
        bot.send_message(message.chat.id, "Принял! Начинаю перерисовывать...")
        file_id = message.photo[-1].file_id
        downloaded_file = bot.download_file(bot.get_file(file_id).file_path)
        image = Image.open(io.BytesIO(downloaded_file))
        response = image_gen_model.generate_content([f"Перерисуй это изображение, следуя инструкции: '{caption}'", image])
        send_generated_image(message.chat.id, response, f"Перерисовано: {caption}", message)
    else:
        bot.reply_to(message, "Я вижу фото. Что мне с ним сделать? Используйте кнопки меню, чтобы выбрать действие.", reply_markup=create_main_menu())

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    try:
        user_text = message.text.strip()
        
        # Кнопки уже обработаны, поэтому здесь их можно игнорировать
        if user_text in ['🖼️ Создать промпт', '🔎 Детальный анализ', '🔤 Перевести текст с фото', '🗑️ Очистить память', '📊 Статус', 'ℹ️ Помощь']:
            return

        draw_keywords = ['нарисуй', 'изобрази', 'сгенерируй']
        if any(keyword in user_text.lower() for keyword in draw_keywords):
            bot.send_message(message.chat.id, "Понял, начинаю рисовать...")
            response = image_gen_model.generate_content(f"Generate a high-quality, masterpiece, 8k, detailed image of: {user_text}")
            send_generated_image(message.chat.id, response, user_text, message)
            return

        # Диалог
        bot.send_chat_action(message.chat.id, 'typing')
        if message.chat.id not in user_chats:
            user_chats[message.chat.id] = vision_model.start_chat(history=[])
        chat = user_chats[message.chat.id]
        response_stream = chat.send_message(user_text, stream=True)
        # Для диалога стриминг оставим, т.к. он тут надежен
        # ... (код стриминга) ...
        full_response = "".join([chunk.text for chunk in response_stream])
        bot.reply_to(message, full_response)

    except Exception as e:
        logger.error(f"Критическая ошибка в handle_text: {e}")
        bot.reply_to(message, "Произошла ошибка. Попробуйте очистить память командой /reset.")

# --- ЗАПУСК БОТА ---
if __name__ == '__main__':
    logger.info("Запускаю веб-сервер в отдельном потоке...")
    threading.Thread(target=run_web_server, daemon=True).start()
    
    logger.info("Запускаю систему 'анти-сон' в отдельном потоке...")
    threading.Thread(target=keep_awake, daemon=True).start()
    
    logger.info("Запускаю бота...")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)