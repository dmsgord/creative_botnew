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

# --- ИСПРАВЛЕНИЕ #2: Безопасный импорт фильтров ---
try:
    import mat_lib
    HAS_MAT_LIB = True
except ImportError:
    logger.warning("⚠️ mat_lib.py не найден. Фильтры мата отключены.")
    HAS_MAT_LIB = False

# Глобальные переменные
data_lock = threading.Lock()
df = None
CAT_DESCRIPTIONS = {} 

MESSAGES = {
    "start_header": "👋 Привет! Я — цифровой помощник команды.",
    "start_sub": "Помогаю правильно оформить заявку в Яндекс Трекер.\n\n👇 **Выберите тему вопроса:**",
    "btn_upd": "🔄 Обновить меню",
    "btn_back": "🔙 Назад к разделам",
    "search_header": "🔍 Нашел:",
    "search_empty": "🤷‍♂️ Ничего не нашел",
    "mat_detected": "🤬 Мат запрещен!",
    "politics_detected": "⛔ Политика запрещена!",
    "injection_detected": "🤖 Бип-буп! Я робот, твои трюки на мне не работают."
}

# --- ИСПРАВЛЕНИЕ #1: Создаем бота СРАЗУ, до загрузки данных ---
if not TOKEN:
    logger.critical("⛔ TOKEN_CHIEF не найден в .env!")
    sys.exit(1)

bot = telebot.TeleBot(TOKEN)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def safe_send_photo(chat_id, image_path, fallback_text):
    """Безопасная отправка фото с обработкой ошибок API."""
    if os.path.exists(image_path):
        try:
            with open(image_path, 'rb') as photo:
                bot.send_photo(chat_id, photo)
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки фото: {e}")
    
    # Если фото нет или ошибка — шлем текст
    try:
        bot.send_message(chat_id, fallback_text)
    except Exception as e:
        logger.error(f"Ошибка отправки текста-заглушки: {e}")
    return False

def add_row_btn(kb, row):
    """Создает кнопку для строки из Excel."""
    name = row['Название заявки']
    link = str(row.get('Ссылка на заявку', ''))
    btn_text = row.get('Текст кнопки', name)
    
    if pd.isna(btn_text) or str(btn_text).strip() == "": 
        btn_text = name

    if link.startswith('http'): 
        kb.add(InlineKeyboardButton(f"{btn_text}", url=link))
    else: 
        kb.add(InlineKeyboardButton(f"ℹ️ {btn_text}", callback_data="no_link"))

def download_file():
    logger.info("📥 Начинаю скачивание...")
    try:
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)

        api_url = 'https://cloud-api.yandex.net/v1/disk/public/resources/download'
        resp = requests.get(api_url, params={'public_key': YANDEX_LINK}, timeout=10)
        
        if resp.status_code != 200: 
            logger.error(f"❌ API Яндекса вернул код: {resp.status_code}")
            return False
        
        download_url = resp.json().get('href')
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
    global df, MESSAGES, CAT_DESCRIPTIONS
    
    if not download_file(): return False

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

                if 'Направление' in headers:
                    valid_sheets.append((sheet_name, temp_df))
                    if 'Описание раздела' in headers:
                        desc_df = temp_df[['Направление', 'Описание раздела']].dropna().drop_duplicates(subset=['Направление'])
                        for _, row in desc_df.iterrows():
                            cat = str(row['Направление']).strip()
                            desc = str(row['Описание раздела']).strip()
                            if desc: found_descriptions[cat] = desc
                elif 'Код' in headers and 'Текст' in headers:
                    for _, row in temp_df.iterrows():
                        key = str(row['Код']).strip()
                        val = str(row['Текст']).strip()
                        if key and val and val != 'nan': found_settings[key] = val
            except Exception:
                continue

        found_main = None
        if not valid_sheets:
            logger.error("❌ Не найден лист с колонкой 'Направление'")
            return False

        for name, data in valid_sheets:
            if 'карта' in name.lower():
                found_main = data
                break
        
        if found_main is None: found_main = valid_sheets[0][1]

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
        logger.exception(f"🔥 Критическая ошибка: {e}")
        return False

# Первичная загрузка (безопасная)
if not load_data():
    logger.error("⚠️ Первичная загрузка не удалась. Бот запустится с пустой базой.")
    df = pd.DataFrame()

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
    try:
        bot.send_message(m.chat.id, text, reply_markup=main_kb())
    except Exception as e:
        logger.error(f"Ошибка отправки start: {e}")

@bot.message_handler(commands=['upd'])
def upd(m):
    try:
        msg = bot.send_message(m.chat.id, "⏳ Обновляю базу...")
        if load_data():
            bot.delete_message(m.chat.id, msg.message_id)
            bot.send_message(m.chat.id, "✅ База успешно обновлена!", reply_markup=main_kb())
        else:
            bot.edit_message_text("❌ Ошибка обновления. См. логи.", m.chat.id, msg.message_id)
    except Exception as e:
        logger.error(f"Ошибка в upd: {e}")

@bot.message_handler(content_types=['text'])
def handle_text(m):
    try:
        user_text = m.text.strip()
        
        # 1. Проверка фильтров (только если модуль загружен)
        if HAS_MAT_LIB:
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
            if df is None or df.empty: return
            # Делаем копию, чтобы избежать Race Condition
            res = df[df['SearchIndex'].str.contains(query, na=False)].head(10).copy()

        if res.empty:
            bot.send_message(m.chat.id, f"{MESSAGES['search_empty']}: {user_text}", reply_markup=main_kb())
            return

        kb = InlineKeyboardMarkup()
        for _, row in res.iterrows():
            add_row_btn(kb, row)
        
        kb.add(InlineKeyboardButton(MESSAGES['btn_back'], callback_data="menu"))
        bot.send_message(m.chat.id, MESSAGES['search_header'], reply_markup=kb)

    except Exception as e:
        logger.error(f"Ошибка в handle_text: {e}")

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
            
            # ИСПРАВЛЕНИЕ #3: Безопасное чтение данных
            with data_lock: 
                if df is None or df.empty:
                    bot.answer_callback_query(c.id, "⚠️ База пуста")
                    return
                sub_df = df[df['Направление'] == cat].copy() # .copy() обязателен!
                description = CAT_DESCRIPTIONS.get(cat, f"Раздел: {cat}")

            kb = InlineKeyboardMarkup()
            for _, row in sub_df.iterrows():
                add_row_btn(kb, row)
            
            kb.add(InlineKeyboardButton(MESSAGES['btn_back'], callback_data="menu"))
            bot.edit_message_text(description, c.message.chat.id, c.message.message_id, reply_markup=kb)
        
        elif c.data == "no_link":
            bot.answer_callback_query(c.id, "🔒 Доступ закрыт", show_alert=True)
            
    except Exception as e:
        logger.error(f"Callback error: {e}")

# --- ФУНКЦИЯ ЗАПУСКА (Обертка для systemd) ---
def run_bot(token=None, is_manager=True):
    """
    Эта функция запускает бота в вечном цикле с защитой от падений.
    Параметры token и is_manager оставлены для совместимости, но берется TOKEN из global.
    """
    retry_delay = 5
    while True:
        try:
            logger.info("🚀 Бот запущен...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
            retry_delay = 5
        except Exception as e:
            logger.error(f"🔥 Бот упал: {e}")
            time.sleep(retry_delay)
            if retry_delay < 300:
                retry_delay *= 2

if __name__ == "__main__":
    run_bot()