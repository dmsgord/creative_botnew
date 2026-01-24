from config import TOKEN_CHIEF
from bot_logic import run_bot

if __name__ == "__main__":
    # is_manager=True или False теперь не влияет на фильтры (мы их отключили),
    # но оставим для порядка
    run_bot(TOKEN_CHIEF, is_manager=True)