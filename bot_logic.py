import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import pandas as pd
import requests
import os
import time
import logging
import threading
import sys
from dotenv import load_dotenv
from python_calamine import CalamineWorkbook 
import mat_lib 

# --- НАСТРОЙКИ ---
load_dotenv()
TOKEN = os.getenv("TOKEN_CHIEF")
YANDEX_LINK = os.getenv("YANDEX_LINK")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_FILE = os.path.join(BASE_DIR, "temp_data.xlsx")

# ПУТИ К КАРТИНКАМ
BAD_IMAGE_PATH = os.path.join(BASE_DIR, "img", "stop.jpg")
POLITICS_IMAGE_PATH = os.path.join(BASE_DIR, "img", "politics.jpg")
ROBOT_IMAGE_PATH = os.path.join(BASE_DIR, "img", "robot.jpg")

# Логирование
logging.basicConfig(
    filename='bot_log.log', 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Глобальные переменные
data_lock = threading.Lock()
df = None
CAT_DESCRIPTIONS = {} 

# Сообщения по умолчанию
MESSAGES = {
    "start_header": "👋 Привет! Я — цифровой помощник команды.",
    "start_sub": "Помогаю правильно оформить заявку в Яндекс Трекер, чтобы коллеги из операционного департамента решили вопрос быстрее.\n\n👇 **Выберите тему вопроса:**",
    "btn_upd": "🔄 Обновить меню",
    "btn_back": "🔙 Назад к разделам",
    "search_header": "🔍 Нашел:",
    "search_empty": "🤷‍♂️ Ничего не нашел",
    "mat_detected": "🤬 Мат запрещен!",
    "politics_detected": "⛔ Политика запрещена!",
    "injection_detected": "🤖 Бип-буп! Я робот, твои трюки на мне не работают."
}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def safe_send_photo(chat_id, image_path, fallback_text):
    """Безопасная отправка фото. Если не вышло — шлет текст."""
    if os.path.exists(image_path):
        try:
            with open(image_path, 'rb') as photo:
                bot.send_photo(chat_id, photo)
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки фото {image_path}: {e}")
    
    # Если файла нет или ошибка — шлем текст
    bot.send_message(chat_id, fallback_text)
    return False

def add_row_btn(kb, row):
    """Создает кнопку для строки из Excel (DRY принцип)."""
    name = row['Название заявки']
    link = str(row.get('Ссылка на заявку', ''))
    btn_text = row.get('Текст кнопки', name)
    
    # Если текст кнопки пустой (NaN или пробелы), берем название заявки
    if pd.isna(btn_text) or str(btn_text).strip() == "": 
        btn_text = name

    # Логика кнопок (без стрелок, как просили)
    if link.startswith('http'): 
        kb.add(InlineKeyboardButton(f"{btn_text}", url=link))
    else: 
        kb.add(InlineKeyboardButton(f"ℹ️ {btn_text}", callback_data="no_link"))

def download_file():
    """Скачивает файл с защитой от кэша и очисткой старого."""
    logger.info("📥 Начинаю скачивание...")
    try:
        # 1. Чистим старый файл
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)

        # 2. Получаем ссылку
        api_url = 'https://cloud-api.yandex.net/v1/disk/public/resources/download'
        resp = requests.get(api_url, params={'public_key': YANDEX_LINK}, timeout=10)
        
        if resp.status_code != 200: 
            logger.error(f"❌ API Яндекса вернул код: {resp.status_code}")
            return False
        
        download_url = resp.json().get('href')
        
        # 3. Скачиваем (добавляем timestamp против кэша)
        ts = int(time.time())
        file_resp = requests.get(download_url, params={'t': ts}, stream=True, timeout=30)
        
        with open(TEMP_FILE, 'wb') as f:
            for chunk in file_resp.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logger.info("✅ Файл успешно скачан.")
        return True
    except Exception as e:
        logger.error(f"🔥 Ошибка скачивания: {e}")
        return False

def load_data():
    """Читает Excel, ищет правильный лист и обновляет глобальные переменные."""
    global df, MESSAGES, CAT_DESCRIPTIONS
    
    if not download_file():
        return False

    try:
        wb = CalamineWorkbook.from_path(TEMP_FILE)
        
        found_settings = {}
        found_descriptions = {}
        valid_sheets = [] 

        for sheet_name in wb.sheet_names:
            try:
                rows = wb.get_sheet_by_name(sheet_name).to_python()
                if not rows: continue
                
                headers = [str(h).strip() for h in rows[0]]
                temp_df = pd.DataFrame(rows[1:], columns=headers)

                # Ищем данные (Направление)
                if 'Направление' in headers:
                    valid_sheets.append((sheet_name, temp_df))
                    
                    if 'Описание раздела' in headers:
                        desc_df = temp_df[['Направление', 'Описание раздела']].dropna().drop_duplicates(subset=['Направление'])
                        for _, row in desc_df.iterrows():
                            cat = str(row['Направление']).strip()
                            desc = str(row['Описание раздела']).strip()
                            if desc: found_descriptions[cat] = desc

                # Ищем настройки (Код, Текст)
                elif 'Код' in headers and 'Текст' in headers:
                    for _, row in temp_df.iterrows():
                        key = str(row['Код']).strip()
                        val = str(row['Текст']).strip()
                        if key and val and val != 'nan': found_settings[key] = val
            except Exception as e:
                logger.warning(f"Ошибка чтения листа {sheet_name}: {e}")
                continue

        # Выбираем лучший лист
        found_main = None
        if not valid_sheets:
            logger.error("❌ Не найден лист с колонкой 'Направление'")
            return False

        # Приоритет: лист с названием "карта"
        for name, data in valid_sheets:
            if 'карта' in name.lower():
                found_main = data
                break
        
        # Если нет, берем первый
        if found_main is None:
            found_main = valid_sheets[0][1]

        # Нормализация
        found_main['Направление'] = found_main['Направление'].astype(str)
        found_main['Название заявки'] = found_main['Название заявки'].fillna("")
        if 'Теги' not in found_main.columns: found_main['Теги'] = ""
        
        found_main['SearchIndex'] = (found_main['Название заявки'].astype(str) + " " + found_main['Теги'].astype(str)).str.lower()

        with data_lock:
            df = found_main
            CAT_DESCRIPTIONS = found_descriptions
            if found_settings: MESSAGES.update(found_settings)
            
        logger.info(f"📊 База обновлена. Строк: {len(df)}")
        return True

    except Exception as e:
        logger.exception(f"🔥 Критическая ошибка парсинга Excel: {e}")
        return False

# Инициализация бота
if not TOKEN:
    print("⛔ ОШИБКА: TOKEN_CHIEF не найден в .env!")
    sys.exit(1)

# Загружаем данные при старте
load_data()
bot = telebot.TeleBot(TOKEN)

# --- ИНТЕРФЕЙС ---

def main_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    with data_lock:
        if df is None or df.empty:
            kb.add(InlineKeyboardButton(MESSAGES['btn_upd'], callback_data="update"))
            return kb
        
        cats = sorted(df['Направление'].unique())
        btns = [InlineKeyboardButton(c, callback_data=f"c|{c}") for c in cats if c != 'nan']
        kb.add(*btns)
    return kb

# --- ХЕНДЛЕРЫ ---

@bot.message_handler(commands=['start'])
def start(m):
    text = f"{MESSAGES['start_header']}\n\n{MESSAGES['start_sub']}"
    bot.send_message(m.chat.id, text, reply_markup=main_kb())

@bot.message_handler(commands=['upd'])
def upd(m):
    msg = bot.send_message(m.chat.id, "⏳ Обновляю базу...")
    if load_data():
        bot.delete_message(m.chat.id, msg.message_id)
        bot.send_message(m.chat.id, "✅ База успешно обновлена!", reply_markup=main_kb())
    else:
        bot.edit_message_text("❌ Ошибка обновления. См. логи.", m.chat.id, msg.message_id)

@bot.message_handler(content_types=['text'])
def handle_text(m):
    user_text = m.text.strip()
    
    # 1. Проверка фильтров
    check_result = mat_lib.check_text(user_text)

    if check_result == 'injection':
        safe_send_photo(m.chat.id, ROBOT_IMAGE_PATH, MESSAGES['injection_detected'])
        return

    if check_result == 'mat':
        safe_send_photo(m.chat.id, BAD_IMAGE_PATH, MESSAGES['mat_detected'])
        return

    if check_result == 'politics':
        safe_send_photo(m.chat.id, POLITICS_IMAGE_PATH, MESSAGES['politics_detected'])
        return

    # 2. Поиск
    query = user_text.lower()
    if len(query) < 2: return

    with data_lock:
        if df is None: return
        res = df[df['SearchIndex'].str.contains(query, na=False)].head(10)

    if res.empty:
        bot.send_message(m.chat.id, f"{MESSAGES['search_empty']}: {user_text}", reply_markup=main_kb())
        return

    kb = InlineKeyboardMarkup()
    for _, row in res.iterrows():
        add_row_btn(kb, row) # Используем новую функцию
    
    kb.add(InlineKeyboardButton(MESSAGES['btn_back'], callback_data="menu"))
    bot.send_message(m.chat.id, MESSAGES['search_header'], reply_markup=kb)

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    try:
        if c.data == "menu":
            text = f"{MESSAGES['start_header']}\n\n{MESSAGES['start_sub']}"
            bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=main_kb())
        
        elif c.data == "update":
            bot.answer_callback_query(c.id, "⏳ Обновляю...")
            if load_data():
                bot.answer_callback_query(c.id, "✅")
                try: bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=main_kb())
                except: pass
            else: 
                bot.answer_callback_query(c.id, "❌ Ошибка")
        
        elif c.data.startswith("c|"):
            cat = c.data.split("|")[1]
            
            with data_lock: 
                sub_df = df[df['Направление'] == cat]
                description = CAT_DESCRIPTIONS.get(cat, f"Раздел: {cat}")

            kb = InlineKeyboardMarkup()
            for _, row in sub_df.iterrows():
                add_row_btn(kb, row) # Используем новую функцию
            
            kb.add(InlineKeyboardButton(MESSAGES['btn_back'], callback_data="menu"))
            bot.edit_message_text(description, c.message.chat.id, c.message.message_id, reply_markup=kb)
        
        elif c.data == "no_link":
            bot.answer_callback_query(c.id, "🔒 Доступ закрыт", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка в callback: {e}")

# --- ЗАПУСК С ЗАЩИТОЙ ОТ ПАДЕНИЙ ---
if __name__ == "__main__":
    retry_delay = 5
    while True:
        try:
            logger.info("🚀 Бот запущен...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
            retry_delay = 5 # Сброс при успехе
        except Exception as e:
            logger.error(f"🔥 Бот упал: {e}")
            logger.info(f"⏳ Рестарт через {retry_delay} сек...")
            time.sleep(retry_delay)
            # Увеличиваем ожидание (до 5 минут)
            if retry_delay < 300:
                retry_delay *= 2