import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ADMIN_TG_ID = os.getenv("ADMIN_TG_ID")

# Проверка наличия обязательных переменных
if not all([BOT_TOKEN, GOOGLE_CALENDAR_ID, SERVICE_ACCOUNT_FILE, OPENROUTER_API_KEY]):
    raise ValueError("Не все обязательные переменные окружения определены в .env файле. "
                     "Проверьте BOT_TOKEN, GOOGLE_CALENDAR_ID, SERVICE_ACCOUNT_FILE, OPENROUTER_API_KEY.")

# Проверка существования файла сервисного аккаунта
if SERVICE_ACCOUNT_FILE and not os.path.exists(SERVICE_ACCOUNT_FILE):
    raise FileNotFoundError(f"Файл сервисного аккаунта не найден по пути: {SERVICE_ACCOUNT_FILE}")
