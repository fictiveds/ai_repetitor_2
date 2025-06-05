import asyncio
import logging
import json # Для уведомлений админа
from aiogram import Bot, Dispatcher, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardRemove, BotCommand
from aiogram.fsm.context import FSMContext
# Убрали импорт состояний отсюда, он теперь в states.py

from config import BOT_TOKEN, ADMIN_TG_ID
from handlers import common, booking, cancellation, llm_fallback_handler # Добавили llm_fallback_handler
from states import UserInteraction # Импортируем состояния из states.py

# import calendar_integration # Закомментировано, пока не используется активно
# import llm_integration # Закомментировано, пока не используется активно
# import history_manager # Закомментировано, пока не используется активно

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# Подключение роутеров
dp.include_router(common.router)
dp.include_router(booking.router) # Подключили роутер для записи
dp.include_router(cancellation.router) # Подключили роутер для отмены
# dp.include_router(other_router) # Если был такой плейсхолдер, убираем или заменяем
dp.include_router(llm_fallback_handler.router) # ДОБАВЛЯЕМ В КОНЦЕ!


async def set_commands(bot_instance: Bot): # Переименовал параметр, чтобы не конфликтовал с модулем bot
    commands = [
        BotCommand(command="/start", description="Начать диалог / Перезапустить бота"),
        BotCommand(command="/help", description="Получить помощь"),
        BotCommand(command="/book", description="Записаться на занятие"),
        BotCommand(command="/cancel_lesson", description="Отменить занятие"),
        BotCommand(command="/available_slots", description="Показать свободные слоты")
    ]
    await bot_instance.set_my_commands(commands)
    logger.info("Команды бота установлены.")

@dp.message(Command("help")) # Оставил help в main, или можно вынести в common
async def cmd_help(message: Message):
    help_text = (
        "Я Александр, ваш помощник для записи на занятия к репетитору по физике.\n\n"
        "Вы можете использовать следующие команды:\n"
        "/start - начать или перезапустить диалог\n"
        "/book - начать процесс записи на занятие\n"
        "/cancel_lesson - начать процесс отмены занятия\n"
        "/available_slots - посмотреть ближайшие свободные слоты\n\n"
        "Если у вас есть вопросы, на которые я не могу ответить, "
        "пожалуйста, свяжитесь с репетитором напрямую."
    )
    await message.answer(help_text)

async def main_func(): # Переименовал main в main_func, чтобы не конфликтовать с __main__
    logger.info("Запуск бота...")
    await set_commands(bot)

    if ADMIN_TG_ID:
        try:
            await bot.send_message(ADMIN_TG_ID, "Бот успешно запущен!")
            logger.info(f"Уведомление о запуске отправлено администратору {ADMIN_TG_ID}")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление администратору: {e}")

    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main_func()) # Вызываем main_func
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
