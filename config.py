import os
from dotenv import load_dotenv

# Грузим переменные из .env
load_dotenv()

TOKEN_MATE = os.getenv("TOKEN_MATE")
TOKEN_CHIEF = os.getenv("TOKEN_CHIEF")
YANDEX_LINK = os.getenv("YANDEX_LINK")

if not TOKEN_MATE or not TOKEN_CHIEF:
    raise ValueError("❌ Ошибка: не найдены токены в .env файле")