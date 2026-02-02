import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import pandas as pd
import requests
import os
import time
import logging
import threading
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

logging.basicConfig(filename='bot_log.log', level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

data_lock = threading.Lock()
df = None
CAT_DESCRIPTIONS = {} # Словарь для описаний

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

# --- СКАЧИВАНИЕ ---
def download_file():
    try:
        api_url = 'https://cloud-api.yandex.net/v1/disk/public/resources/download'
        resp = requests.get(api_url, params={'public_key': YANDEX_LINK})
        if resp.status_code != 200: return False
        with open(TEMP_FILE, 'wb') as f:
            f.write(requests.get(resp.json().get('href')).content)
        return True
    except: return False

# --- ЧТЕНИЕ ---
def load_data():
    global df, MESSAGES, CAT_DESCRIPTIONS
    if not download_file(): return False

    try:
        wb = CalamineWorkbook.from_path(TEMP_FILE)
        found_main = None
        found_settings = {}
        found_descriptions = {}

        for sheet_name in wb.sheet_names:
            rows = wb.get_sheet_by_name(sheet_name).to_python()
            if not rows: continue
            headers = [str(h).strip() for h in rows[0]]
            temp_df = pd.DataFrame(rows[1:], columns=headers)

            if 'Направление' in headers:
                found_main = temp_df
                # Ищем колонку с описанием раздела
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

        if found_main is None: return False

        found_main['Направление'] = found_main['Направление'].astype(str)
        found_main['Название заявки'] = found_main['Название заявки'].fillna("")
        if 'Теги' not in found_main.columns: found_main['Теги'] = ""
        
        found_main['SearchIndex'] = (found_main['Название заявки'].astype(str) + " " + found_main['Теги'].astype(str)).str.lower()

        with data_lock:
            df = found_main
            CAT_DESCRIPTIONS = found_descriptions
            if found_settings: MESSAGES.update(found_settings)
        return True
    except Exception as e:
        logger.error(f"Load error: {e}")
        return False

load_data()
bot = telebot.TeleBot(TOKEN)

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

@bot.message_handler(commands=['start'])
def start(m):
    text = f"{MESSAGES['start_header']}\n\n{MESSAGES['start_sub']}"
    bot.send_message(m.chat.id, text, reply_markup=main_kb())

@bot.message_handler(commands=['upd'])
def upd(m):
    msg = bot.send_message(m.chat.id, "⏳ Обновляю...")
    if load_data():
        bot.delete_message(m.chat.id, msg.message_id)
        bot.send_message(m.chat.id, "✅ Меню обновлено!", reply_markup=main_kb())
    else:
        bot.edit_message_text("❌ Ошибка обновления.", m.chat.id, msg.message_id)

@bot.message_handler(content_types=['text'])
def handle_text(m):
    user_text = m.text.strip()
    
    check_result = mat_lib.check_text(user_text)

    if check_result == 'injection':
        if os.path.exists(ROBOT_IMAGE_PATH):
            try:
                with open(ROBOT_IMAGE_PATH, 'rb') as photo:
                    bot.send_photo(m.chat.id, photo)
                return
            except: pass
        bot.reply_to(m, MESSAGES['injection_detected'])
        return

    if check_result == 'mat':
        if os.path.exists(BAD_IMAGE_PATH):
            try:
                with open(BAD_IMAGE_PATH, 'rb') as photo:
                    bot.send_photo(m.chat.id, photo)
                return
            except: pass
        bot.reply_to(m, MESSAGES['mat_detected'])
        return

    if check_result == 'politics':
        if os.path.exists(POLITICS_IMAGE_PATH):
            try:
                with open(POLITICS_IMAGE_PATH, 'rb') as photo:
                    bot.send_photo(m.chat.id, photo)
                return
            except: pass
        bot.reply_to(m, MESSAGES['politics_detected'])
        return

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
        name = row['Название заявки']
        link = str(row.get('Ссылка на заявку', ''))
        btn_text = row.get('Текст кнопки', name)
        if pd.isna(btn_text) or btn_text == "": btn_text = name

        # БЕЗ СТРЕЛОК
        if link.startswith('http'): kb.add(InlineKeyboardButton(f"{btn_text}", url=link))
        else: kb.add(InlineKeyboardButton(f"ℹ️ {btn_text}", callback_data="no_link"))
    
    kb.add(InlineKeyboardButton(MESSAGES['btn_back'], callback_data="menu"))
    bot.send_message(m.chat.id, MESSAGES['search_header'], reply_markup=kb)

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    if c.data == "menu":
        text = f"{MESSAGES['start_header']}\n\n{MESSAGES['start_sub']}"
        bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=main_kb())
    
    elif c.data == "update":
        bot.answer_callback_query(c.id, "⏳ Обновляю...")
        if load_data():
            bot.answer_callback_query(c.id, "✅")
            try: bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=main_kb())
            except: pass
        else: bot.answer_callback_query(c.id, "❌ Ошибка")
    
    elif c.data.startswith("c|"):
        cat = c.data.split("|")[1]
        
        with data_lock: 
            sub_df = df[df['Направление'] == cat]
            # Берем описание из словаря
            description = CAT_DESCRIPTIONS.get(cat, f"Раздел: {cat}")

        kb = InlineKeyboardMarkup()
        for _, row in sub_df.iterrows():
            name = row['Название заявки']
            link = str(row.get('Ссылка на заявку', ''))
            btn_text = row.get('Текст кнопки', name)
            if pd.isna(btn_text) or btn_text == "": btn_text = name
            
            # БЕЗ СТРЕЛОК
            if link.startswith('http'): kb.add(InlineKeyboardButton(f"{btn_text}", url=link))
            else: kb.add(InlineKeyboardButton(f"ℹ️ {btn_text}", callback_data="no_link"))
        
        kb.add(InlineKeyboardButton(MESSAGES['btn_back'], callback_data="menu"))
        
        # Выводим описание раздела
        bot.edit_message_text(description, c.message.chat.id, c.message.message_id, reply_markup=kb)
    
    elif c.data == "no_link":
        bot.answer_callback_query(c.id, "🔒 Доступ закрыт", show_alert=True)

while True:
    try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except: time.sleep(5)