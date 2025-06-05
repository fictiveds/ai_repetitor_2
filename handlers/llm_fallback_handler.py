from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from states import UserInteraction # Для установки общего состояния, если потребуется
from history_manager import get_dialog_history_from_fsm, update_fsm_and_file_history, load_history
from llm_integration import get_llm_response

router = Router()

# Этот хендлер должен быть последним, чтобы ловить все текстовые сообщения,
# которые не были обработаны другими хендлерами (командами, состояниями FSM).
@router.message(F.text) # Фильтр на текстовые сообщения
async def handle_fallback_text_message(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    user_input = message.text if message.text else ""

    # Получаем текущее состояние пользователя
    # current_state = await state.get_state() # Not strictly needed for now as this is a fallback

    # Загружаем историю диалога
    user_fsm_data = await state.get_data()
    # Если это первое сообщение после /start, история уже должна быть в FSM.
    # Если пользователь просто пишет боту без /start, загружаем из файла.
    if 'dialog_history' not in user_fsm_data or not user_fsm_data.get('dialog_history'):
        dialog_history = load_history(user_id)
        # Ensure user_id is also in fsm_data if we are setting dialog_history
        await state.update_data(dialog_history=dialog_history, user_id=user_id if 'user_id' not in user_fsm_data else user_fsm_data.get('user_id'))
    else:
        dialog_history = user_fsm_data['dialog_history']

    # Ensure user_id is present in FSM for history saving, even if history was already there
    if 'user_id' not in user_fsm_data:
        await state.update_data(user_id=user_id)

    await message.answer_chat_action("typing")
    llm_answer = get_llm_response(
        user_id=user_id,
        dialog_history=dialog_history, # type: ignore
        user_input=user_input
    )

    # Сначала обновляем историю с сообщением пользователя, так как оно уже произошло
    await update_fsm_and_file_history(user_id, state, "user", user_input)

    if llm_answer:
        await message.answer(llm_answer)
        await update_fsm_and_file_history(user_id, state, "assistant", llm_answer)
    else:
        fallback_error_message = "Извините, не могу сейчас обработать ваш запрос. Попробуйте позже."
        await message.answer(fallback_error_message)
        await update_fsm_and_file_history(user_id, state, "assistant", fallback_error_message)
