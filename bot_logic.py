import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import pandas as pd
import requests
import os
import time
import logging
from logging.handlers import RotatingFileHandler
import threading
import mat_lib 
from dotenv import load_dotenv

# --- НАСТРОЙКИ ПУТЕЙ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BAD_IMAGE_PATH = os.path.join(BASE_DIR, "img", "stop.jpg")
TEMP_FILE = os.path.join(BASE_DIR, "temp_data.xlsx")
LOG_FILE = os.path.join(BASE_DIR, "bot_log.log")

# --- ЛОГИРОВАНИЕ (FIX: Ротация) ---
# Теперь логи не сожрут весь диск. Максимум 5 МБ, храним 3 архива.
handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[handler, logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- КОНФИГ ---
load_dotenv()
YANDEX_LINK = os.getenv("YANDEX_LINK")

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
data_lock = threading.Lock()
update_lock = threading.Lock() # FIX: Защита от одновременного обновления
last_update_time = 0           # FIX: Для кулдауна
df = None

DEFAULT_MESSAGES = {
    "start_header": "👋 <b>Корпоративный портал</b>",
    "start_sub": "Выберите раздел или напишите запрос (например: <i>отпуск</i>):",
    "cat_prefix": "Раздел: ",
    "cat_sub": "👇 Выберите задачу:",
    "btn_back": "🔙 Назад",
    "btn_upd": "🔄 Обновить меню",
    "msg_lock": "🔒 Информационное сообщение",
    "search_header": "🔍 <b>Нашел вот это:</b>",
    "search_empty": "🤔 <b>Не совсем понял, что вы имели в виду.</b>\n\nПопробуйте переформулировать запрос или перейдите в <b>Главное меню</b> 👇",
    "mat_detected": "Ай-яй-яй! У нас культурное общество 🧐",
    "btn_main_menu": "🏠 В главное меню",
    "wait_update": "⏳ Обновление уже идет или было недавно. Пожалуйста, подождите минуту."
}
MESSAGES = DEFAULT_MESSAGES.copy()

# --- ОЧИСТКА ---
JUNK_WORDS = [
    "Заявка на ", "Заявка ", "Заказ ", "оформление ", 
    "согласование ", "предоставление ", "выдача ", 
    "создание ", "подготовка ", "проведение ", "форма для "
]

def auto_clean_text(text):
    if not isinstance(text, str): return str(text)
    text = text.strip()
    if text.lower().startswith("вопросы по"):
        text = "❓ " + text[10:].strip()
    for junk in JUNK_WORDS:
        if text.lower().startswith(junk):
            text = text[len(junk):].strip()
    if text: text = text[0].upper() + text[1:]
    if len(text) > 40:
        text = text[:37].rsplit(' ', 1)[0] + "..."
    return text

# --- НОРМАЛИЗАЦИЯ ---
def normalize_columns(df_obj):
    rename_map = {}
    for col in df_obj.columns:
        clean_col = str(col).strip().replace('\ufeff', '').lower()
        if 'направление' in clean_col: rename_map[col] = 'Направление'
        elif 'ссылка' in clean_col and 'заявку' in clean_col: rename_map[col] = 'Ссылка на заявку'
        elif 'текст' in clean_col and 'кнопки' in clean_col: rename_map[col] = 'Текст кнопки'
        elif 'название' in clean_col and 'заявки' in clean_col: rename_map[col] = 'Название заявки'
        elif 'теги' in clean_col or 'tags' in clean_col: rename_map[col] = 'Теги'
        elif clean_col == 'код': rename_map[col] = 'Код'
        elif clean_col == 'текст': rename_map[col] = 'Текст'
    if rename_map:
        df_obj = df_obj.rename(columns=rename_map)
    return df_obj

# --- ЗАГРУЗКА ---
def load_data():
    global df, MESSAGES
    
    # FIX: Защита от одновременного запуска (Race Condition)
    if update_lock.locked():
        logger.warning("⚠️ Попытка параллельного обновления отклонена")
        return False
        
    with update_lock:
        logger.info("=========================================")
        logger.info("🔄 ЗАГРУЗКА БАЗЫ")
        
        if not YANDEX_LINK:
            logger.error("❌ .env пуст или YANDEX_LINK не найден")
            return False

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        try:
            api_url = 'https://cloud-api.yandex.net/v1/disk/public/resources/download'
            resp = requests.get(api_url, params={'public_key': YANDEX_LINK}, headers=headers, timeout=15)
            
            if resp.status_code != 200:
                logger.error(f"❌ Яндекс отклонил запрос. Код: {resp.status_code}")
                return False
                
            download_url = resp.json().get('href')
            
            logger.info("📥 Скачиваю файл...")
            file_resp = requests.get(download_url, headers=headers, stream=True, timeout=30)
            
            with open(TEMP_FILE, 'wb') as f:
                for chunk in file_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info("✅ Файл сохранен.")

            # FIX: Безопасное чтение Excel (with ... context manager)
            # Это предотвращает утечку памяти
            found_data_df = None
            new_messages = DEFAULT_MESSAGES.copy()

            engines = ['openpyxl', 'calamine']
            xls_obj = None

            for eng in engines:
                try:
                    # Открываем файл в контекстном менеджере
                    with pd.ExcelFile(TEMP_FILE, engine=eng) as xls:
                        logger.info(f"📖 Читаю через {eng}...")
                        
                        for sheet in xls.sheet_names:
                            try:
                                if eng == 'calamine':
                                    temp_df = pd.read_excel(xls, sheet_name=sheet, engine='calamine')
                                else:
                                    temp_df = pd.read_excel(xls, sheet_name=sheet)
                                
                                temp_df = normalize_columns(temp_df)
                                cols = temp_df.columns.tolist()
                                
                                if 'Направление' in cols:
                                    logger.info(f"   ✅ БАЗА: {sheet}")
                                    found_data_df = temp_df
                                elif 'Код' in cols and 'Текст' in cols:
                                    logger.info(f"   ⚙️ НАСТРОЙКИ: {sheet}")
                                    for _, row in temp_df.iterrows():
                                        key = str(row['Код']).strip()
                                        val = str(row['Текст']).strip()
                                        if key in new_messages and val and val != 'nan':
                                            new_messages[key] = val
                            except: pass
                    
                    if found_data_df is not None:
                        break # Если успешно прочитали, выходим из цикла движков

                except Exception as e:
                    logger.warning(f"⚠️ Движок {eng} не справился: {e}")

            if found_data_df is None: 
                logger.error("❌ Не удалось прочитать Excel ни одним движком")
                return False

            # Обработка данных
            found_data_df['Направление'] = found_data_df['Направление'].astype(str)
            if 'Текст кнопки' not in found_data_df.columns: found_data_df['Текст кнопки'] = None
            if 'Теги' not in found_data_df.columns: found_data_df['Теги'] = ""
            else: found_data_df['Теги'] = found_data_df['Теги'].fillna("").astype(str).str.lower()
            
            found_data_df['SearchIndex'] = (
                found_data_df['Название заявки'].fillna("").astype(str).str.lower() + " " + 
                found_data_df['Теги']
            )

            with data_lock:
                df = found_data_df.copy()
                MESSAGES = new_messages
                
            logger.info(f"✅ УСПЕХ! Строк: {len(df)}")
            return True

        except Exception as e:
            logger.exception("🔥 ОШИБКА ПРИ ОБНОВЛЕНИИ:")
            return False

if not load_data():
    with data_lock: df = pd.DataFrame()

# --- БОТ ---
def run_bot(token, is_manager=True):
    bot = telebot.TeleBot(token)
    logger.info(f"🚀 Бот запущен. Картинка: {BAD_IMAGE_PATH}")

    def get_msg(key):
        with data_lock: return MESSAGES.get(key, DEFAULT_MESSAGES.get(key, ""))

    def get_data(cat=None):
        with data_lock:
            if df is None or df.empty: return pd.DataFrame()
            local_df = df.copy()
        if cat: local_df = local_df[local_df['Направление'] == cat]
        return local_df

    def main_kb():
        kb = InlineKeyboardMarkup(row_width=2)
        with data_lock: empty = (df is None or df.empty)
        if empty:
            kb.add(InlineKeyboardButton(get_msg("btn_upd"), callback_data="update"))
            return kb
        cats = sorted([x for x in get_data()['Направление'].unique() if str(x) != 'nan'])
        btns = [InlineKeyboardButton(str(c).strip(), callback_data=f"c|{c}") for c in cats]
        kb.add(*btns)
        kb.add(InlineKeyboardButton(get_msg("btn_upd"), callback_data="update"))
        return kb

    def generate_links_kb(data_rows, back_btn=True):
        kb = InlineKeyboardMarkup(row_width=1)
        for _, row in data_rows.iterrows():
            btn_text = row['Текст кнопки'] if pd.notna(row['Текст кнопки']) and str(row['Текст кнопки']).strip() != "" else None
            if not btn_text: btn_text = auto_clean_text(row['Название заявки'])
            link = str(row['Ссылка на заявку'])
            if link.startswith('http'): kb.add(InlineKeyboardButton(f"{btn_text} ↗️", url=link))
            else: kb.add(InlineKeyboardButton(f"ℹ️ {btn_text}", callback_data="no"))
        if back_btn: kb.add(InlineKeyboardButton(get_msg("btn_back"), callback_data="menu"))
        return kb

    @bot.message_handler(commands=['start'])
    def start(m):
        bot.send_message(m.chat.id, f"{get_msg('start_header')}\n{get_msg('start_sub')}", reply_markup=main_kb(), parse_mode='HTML')

    @bot.message_handler(commands=['upd', 'update'])
    def upd(m):
        global last_update_time
        
        # FIX: Rate Limiting (Защита от спама)
        now = time.time()
        if now - last_update_time < 60: # 60 секунд задержка
            bot.send_message(m.chat.id, get_msg("wait_update"))
            return

        bot.send_chat_action(m.chat.id, 'typing')
        last_update_time = now # Обновляем время
        
        if load_data(): bot.send_message(m.chat.id, f"✅ {get_msg('btn_upd')} выполнено!")
        else: bot.send_message(m.chat.id, "❌ Ошибка обновления.")

    # --- ТЕКСТ ---
    @bot.message_handler(content_types=['text'])
    def handle_text(m):
        user_text = m.text.strip()
        
        if mat_lib.check_text(user_text):
            if os.path.exists(BAD_IMAGE_PATH):
                try:
                    with open(BAD_IMAGE_PATH, 'rb') as photo:
                        bot.send_photo(m.chat.id, photo)
                except:
                    bot.reply_to(m, get_msg("mat_detected"))
            else:
                bot.reply_to(m, get_msg("mat_detected"))
            return

        query = user_text.lower()
        if len(query) < 2: return 

        with data_lock:
            if df is None or df.empty: return
            results = df[df['SearchIndex'].str.contains(query, regex=False, na=False)]
        
        if not results.empty:
            results = results.head(10)
            bot.send_message(m.chat.id, get_msg("search_header"), reply_markup=generate_links_kb(results), parse_mode='HTML')
        else:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton(get_msg("btn_main_menu"), callback_data="menu"))
            bot.send_message(m.chat.id, get_msg("search_empty"), reply_markup=kb, parse_mode='HTML')

    @bot.callback_query_handler(func=lambda c: True)
    def cb(c):
        global last_update_time
        try:
            if c.data == "menu":
                text = f"{get_msg('start_header')}\n{get_msg('start_sub')}"
                bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=main_kb(), parse_mode='HTML')
            
            elif c.data == "update":
                # FIX: Проверка кулдауна для кнопки
                now = time.time()
                if now - last_update_time < 60:
                    bot.answer_callback_query(c.id, "⏳ Подождите минуту перед обновлением")
                    return
                
                last_update_time = now
                bot.answer_callback_query(c.id, "⏳ Загружаю...")
                
                if load_data(): 
                    bot.answer_callback_query(c.id, "✅ Готово")
                    try: bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=main_kb())
                    except: pass
                else: bot.answer_callback_query(c.id, "❌ Ошибка")
            
            elif c.data.startswith("c|"):
                cat = c.data.split("|")[1]
                header = f"{get_msg('cat_prefix')} <b>{cat}</b>"
                sub = get_msg('cat_sub')
                cat_data = get_data(cat)
                bot.edit_message_text(f"{header}\n\n{sub}", c.message.chat.id, c.message.message_id, reply_markup=generate_links_kb(cat_data), parse_mode='HTML')
            elif c.data == "no":
                bot.answer_callback_query(c.id, get_msg("msg_lock"), show_alert=True)
            bot.answer_callback_query(c.id)
        except Exception as e: logger.error(e)

    while True:
        try: bot.infinity_polling(timeout=50, long_polling_timeout=30)
        except: time.sleep(5)