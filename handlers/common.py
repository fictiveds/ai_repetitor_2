from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from states import UserInteraction
from history_manager import update_fsm_and_file_history, load_history
from llm_integration import get_llm_response # Добавили импорт LLM

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id # type: ignore
    user_input_for_llm = message.text if message.text else "/start" # Что пользователь фактически написал

    # Загружаем историю или начинаем новую
    dialog_history = load_history(user_id)
    await state.update_data(user_id=user_id, dialog_history=dialog_history) # Сохраняем user_id и пустую/загруженную историю в FSM

    # Первое сообщение пользователя уже есть в user_input_for_llm
    # Мы не добавляем его в dialog_history перед первым вызовом LLM,
    # так как get_llm_response ожидает dialog_history (прошлое) и user_input (текущее) раздельно.

    await message.answer_chat_action("typing")
    # Получаем приветствие от LLM.
    # dialog_history тут будет пустой при первом старте или содержать предыдущие диалоги.
    # user_input - это команда /start или текст, который пользователь мог написать вместе с /start.
    initial_llm_response = get_llm_response(
        user_id=user_id,
        dialog_history=dialog_history, # Может быть не пустой, если пользователь продолжает диалог # type: ignore
        user_input=user_input_for_llm # "/start" или "/start какой-то текст"
    )

    if not initial_llm_response:
        # Фоллбэк, если LLM не ответил
        initial_llm_response = (
            "Здравствуйте! Я Александр, AI-помощник репетитора по физике Юрия Фёдоровича. "
            "Готов помочь вам записаться на занятие или ответить на ваши вопросы по процессу записи.\n\n"
            "Скажите, пожалуйста, какова цель вашего обращения? "
            "Например: подготовка к ЕГЭ, ОГЭ, ВПР, помощь со школьной программой, повышение успеваемости и т.д."
        )

    await message.answer(initial_llm_response)

    # Сохраняем сообщение пользователя и ответ бота в историю
    # Важно: user_input_for_llm - это то, что пользователь ВВЕЛ (например, "/start")
    # initial_llm_response - это то, что ОТВЕТИЛ бот.
    await update_fsm_and_file_history(user_id, state, "user", user_input_for_llm)
    await update_fsm_and_file_history(user_id, state, "assistant", initial_llm_response)

    # После приветствия от LLM, бот должен ожидать цель обращения.
    # Системный промпт подразумевает, что LLM сам задаст вопрос о цели, если это необходимо.
    # Поэтому установка UserInteraction.awaiting_purpose здесь может быть избыточной,
    # если LLM уже задал этот вопрос.
    # Однако, если мы хотим, чтобы следующий ответ пользователя обрабатывался
    # хендлером process_purpose из booking.py, то состояние нужно установить.
    # Это компромисс между "полностью LLM-driven" и "LLM + FSM".
    # Пока оставим установку состояния, чтобы FSM-логика записи работала.
    await state.set_state(UserInteraction.awaiting_purpose)
