import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import pandas as pd
import requests
import os
import time
import logging
import threading
from dotenv import load_dotenv
from python_calamine import CalamineWorkbook  # <-- Самый надежный инструмент

# --- НАСТРОЙКИ ---
load_dotenv()
TOKEN = os.getenv("TOKEN_CHIEF")
YANDEX_LINK = os.getenv("YANDEX_LINK")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_FILE = os.path.join(BASE_DIR, "temp_data.xlsx")
BAD_IMAGE_PATH = os.path.join(BASE_DIR, "img", "stop.jpg")

# Логирование
logging.basicConfig(
    filename='bot_log.log', 
    level=logging.INFO, 
    format='%(asctime)s - %(message)s', 
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

# Глобальные переменные
data_lock = threading.Lock()
df = None
# Стандартные сообщения (на случай, если лист настроек не прочитается)
MESSAGES = {
    "start_header": "👋 Корпоративный портал",
    "start_sub": "👇 Выберите раздел:",
    "btn_upd": "🔄 Обновить меню",
    "btn_back": "🔙 Назад",
    "search_header": "🔍 Нашел:",
    "search_empty": "🤷‍♂️ Ничего не нашел",
    "cat_prefix": "Раздел: "
}

# --- 1. СКАЧИВАНИЕ ФАЙЛА ---
def download_file():
    logger.info("📥 Скачиваю файл с Яндекса...")
    try:
        api_url = 'https://cloud-api.yandex.net/v1/disk/public/resources/download'
        # Получаем прямую ссылку
        resp = requests.get(api_url, params={'public_key': YANDEX_LINK})
        if resp.status_code != 200:
            logger.error(f"Ошибка API Яндекса: {resp.status_code}")
            return False
        
        download_url = resp.json().get('href')
        
        # Скачиваем сам файл
        file_content = requests.get(download_url).content
        with open(TEMP_FILE, 'wb') as f:
            f.write(file_content)
        
        logger.info("✅ Файл сохранен на диск.")
        return True
    except Exception as e:
        logger.error(f"🔥 Ошибка скачивания: {e}")
        return False

# --- 2. ЧТЕНИЕ EXCEL (HADEZHNO) ---
def load_data():
    global df, MESSAGES
    
    if not download_file():
        return False

    try:
        # Читаем файл "низкоуровневым" способом, который не ломается
        wb = CalamineWorkbook.from_path(TEMP_FILE)
        
        found_main = None
        found_settings = {}

        # Пробегаем по всем листам (Карта, Эмодзи, Настройки)
        for sheet_name in wb.sheet_names:
            rows = wb.get_sheet_by_name(sheet_name).to_python()
            if not rows: continue

            # Создаем временную таблицу
            # Первая строка - заголовки
            headers = [str(h).strip() for h in rows[0]]
            temp_df = pd.DataFrame(rows[1:], columns=headers)

            # --- Ищем лист "Карта" ---
            # Признак: есть колонка "Направление"
            if 'Направление' in headers:
                logger.info(f"📄 Нашел базу данных на листе: {sheet_name}")
                found_main = temp_df
            
            # --- Ищем лист "Настройки" ---
            # Признак: есть колонки "Код" и "Текст"
            elif 'Код' in headers and 'Текст' in headers:
                logger.info(f"⚙️ Нашел настройки на листе: {sheet_name}")
                for _, row in temp_df.iterrows():
                    key = str(row['Код']).strip()
                    val = str(row['Текст']).strip()
                    if key and val and val != 'nan':
                        found_settings[key] = val

        # Если не нашли главную таблицу
        if found_main is None:
            logger.error("❌ В файле нет листа с колонкой 'Направление'")
            return False

        # Обработка данных
        # Чистим пустые значения и приводим к строке
        found_main['Направление'] = found_main['Направление'].astype(str)
        found_main['Название заявки'] = found_main['Название заявки'].fillna("")
        
        # Создаем индекс для поиска (Название + Теги)
        # Если колонки "Теги" нет, создадим пустую
        if 'Теги' not in found_main.columns: 
            found_main['Теги'] = ""
        
        found_main['SearchIndex'] = (
            found_main['Название заявки'].astype(str) + " " + 
            found_main['Теги'].astype(str)
        ).str.lower()

        # Сохраняем в глобальные переменные
        with data_lock:
            df = found_main
            # Обновляем сообщения, если нашли настройки
            if found_settings:
                MESSAGES.update(found_settings)

        logger.info(f"✅ УСПЕХ! Загружено {len(df)} строк.")
        return True

    except Exception as e:
        logger.exception(f"🔥 Ошибка чтения Excel: {e}")
        return False

# --- 3. ЗАПУСК БОТА ---
# Грузим данные при старте
load_data()

bot = telebot.TeleBot(TOKEN)

# Клавиатура главного меню
def main_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    with data_lock:
        if df is None or df.empty:
            kb.add(InlineKeyboardButton(MESSAGES['btn_upd'], callback_data="update"))
            return kb
        
        # Берем уникальные направления
        cats = sorted(df['Направление'].unique())
        btns = [InlineKeyboardButton(c, callback_data=f"c|{c}") for c in cats if c != 'nan']
        kb.add(*btns)
        kb.add(InlineKeyboardButton(MESSAGES['btn_upd'], callback_data="update"))
    return kb

@bot.message_handler(commands=['start'])
def start(m):
    text = f"{MESSAGES['start_header']}\n{MESSAGES['start_sub']}"
    bot.send_message(m.chat.id, text, reply_markup=main_kb())

@bot.message_handler(commands=['upd'])
def upd(m):
    msg = bot.send_message(m.chat.id, "⏳ Скачиваю и обновляю...")
    if load_data():
        bot.edit_message_text("✅ Готово! Меню обновлено.", m.chat.id, msg.message_id)
        # Показываем новое меню
        bot.send_message(m.chat.id, f"{MESSAGES['start_header']}", reply_markup=main_kb())
    else:
        bot.edit_message_text("❌ Ошибка. Проверь файл (нужна колонка 'Направление') или логи.", m.chat.id, msg.message_id)

@bot.message_handler(content_types=['text'])
def handle_text(m):
    # 1. Проверка на мат (если есть)
    # (Здесь простая заглушка, чтобы не усложнять код, если библиотеки нет)
    # Если нужно - раскомментируй импорт mat_lib
    
    # 2. Поиск
    query = m.text.lower().strip()
    if len(query) < 2: return

    with data_lock:
        if df is None: return
        # Ищем совпадения
        res = df[df['SearchIndex'].str.contains(query, na=False)].head(10)

    if res.empty:
        bot.send_message(m.chat.id, MESSAGES['search_empty'], reply_markup=main_kb())
        return

    # Формируем кнопки с результатами
    kb = InlineKeyboardMarkup()
    for _, row in res.iterrows():
        name = row['Название заявки']
        link = str(row.get('Ссылка на заявку', ''))
        
        # Если есть колонка "Текст кнопки", берем её, иначе название
        btn_text = row.get('Текст кнопки', name)
        if pd.isna(btn_text) or btn_text == "": btn_text = name

        if link.startswith('http'):
            kb.add(InlineKeyboardButton(f"{btn_text} ↗️", url=link))
        else:
            kb.add(InlineKeyboardButton(f"ℹ️ {btn_text}", callback_data="no_link"))
    
    kb.add(InlineKeyboardButton(MESSAGES['btn_back'], callback_data="menu"))
    bot.send_message(m.chat.id, f"{MESSAGES['search_header']}", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    if c.data == "menu":
        text = f"{MESSAGES['start_header']}\n{MESSAGES['start_sub']}"
        bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=main_kb())
    
    elif c.data == "update":
        bot.answer_callback_query(c.id, "⏳ Обновляю...")
        if load_data():
            bot.answer_callback_query(c.id, "✅ Успешно")
            try: bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=main_kb())
            except: pass
        else:
            bot.answer_callback_query(c.id, "❌ Ошибка")

    elif c.data.startswith("c|"):
        category = c.data.split("|")[1]
        with data_lock:
            # Фильтруем по категории
            sub_df = df[df['Направление'] == category]
        
        kb = InlineKeyboardMarkup()
        for _, row in sub_df.iterrows():
            name = row['Название заявки']
            link = str(row.get('Ссылка на заявку', ''))
            
            btn_text = row.get('Текст кнопки', name)
            if pd.isna(btn_text) or btn_text == "": btn_text = name

            if link.startswith('http'):
                kb.add(InlineKeyboardButton(f"{btn_text} ↗️", url=link))
            else:
                kb.add(InlineKeyboardButton(f"ℹ️ {btn_text}", callback_data="no_link"))
        
        kb.add(InlineKeyboardButton(MESSAGES['btn_back'], callback_data="menu"))
        
        prefix = MESSAGES.get('cat_prefix', 'Раздел: ')
        bot.edit_message_text(f"{prefix} {category}", c.message.chat.id, c.message.message_id, reply_markup=kb)

    elif c.data == "no_link":
        bot.answer_callback_query(c.id, "🔒 Доступ закрыт или ссылка не указана", show_alert=True)

# Вечный цикл запуска
while True:
    try:
        logger.info("🚀 Бот запускается...")
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        logger.error(f"Упал: {e}")
        time.sleep(5)