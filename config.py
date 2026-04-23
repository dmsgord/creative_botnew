import os
from dotenv import load_dotenv

load_dotenv()

TOKEN_CHIEF = os.getenv("TOKEN_CHIEF")
YANDEX_LINK = os.getenv("YANDEX_LINK")

if not TOKEN_CHIEF:
    raise ValueError("❌ Ошибка: TOKEN_CHIEF не найден в .env")