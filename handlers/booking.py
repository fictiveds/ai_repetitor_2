from aiogram import Router, F, Bot
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
import json

from states import UserInteraction
from calendar_integration import get_available_slots, create_calendar_event, EventCreate, TUTOR_TIMEZONE
from config import ADMIN_TG_ID
from history_manager import update_fsm_and_file_history, load_history # Добавлен импорт

router = Router()

# --- Этап 1: Получение цели обращения (уже инициировано в common.py) ---
@router.message(UserInteraction.awaiting_purpose, F.text)
async def process_purpose(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    purpose = message.text
    await update_fsm_and_file_history(user_id, state, "user", purpose if purpose else "") # ИСТОРИЯ

    await state.update_data(purpose=purpose)

    info_text = (
        "Занятия проходят онлайн, индивидуально. "
        "Время работы репетитора: с 17:00 до 22:00 по МСК (обычно по будням).\n\n"
        "Стоимость занятий:\n"
        "- Школьная программа: 1000-1200₽/час\n"
        "- Подготовка к ЕГЭ/ОГЭ: 1200-1500₽/час\n"
        "- Подготовка к ВПР: 1000-1200₽/час\n"
        "Пробный урок оплачивается по той же стоимости.\n\n"
        "Предлагаю вам записаться на пробный урок. Показать доступные слоты на ближайшие дни?"
    )

    await message.answer(info_text, reply_markup=ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Да, показать слоты")],
            [KeyboardButton(text="Нет, спасибо")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    ))
    await update_fsm_and_file_history(user_id, state, "assistant", info_text) # ИСТОРИЯ

# --- Этап 2: Предложение показать слоты и выбор времени ---
@router.message(UserInteraction.awaiting_purpose, F.text == "Да, показать слоты")
async def show_available_slots(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    await update_fsm_and_file_history(user_id, state, "user", message.text if message.text else "") # ИСТОРИЯ

    response_text_searching = "Ищу свободные слоты..."
    await message.answer(response_text_searching, reply_markup=ReplyKeyboardRemove())
    await update_fsm_and_file_history(user_id, state, "assistant", response_text_searching) # ИСТОРИЯ

    try:
        available_slots_dt = get_available_slots(days=7)
    except Exception as e:
        error_text = "Произошла ошибка при получении слотов. Попробуйте позже или напишите репетитору."
        await message.answer(error_text)
        await update_fsm_and_file_history(user_id, state, "assistant", error_text) # ИСТОРИЯ
        return

    if not available_slots_dt:
        no_slots_text = (
            "К сожалению, на ближайшие 7 дней свободных слотов нет. "
            "Вы можете проверить позже или написать репетитору напрямую для уточнения возможных вариантов."
        )
        await message.answer(no_slots_text)
        await update_fsm_and_file_history(user_id, state, "assistant", no_slots_text) # ИСТОРИЯ
        await state.clear()
        return

    slot_buttons = []
    slots_to_show = available_slots_dt[:15]
    shown_slots_data_for_fsm = {}

    for slot_dt in slots_to_show:
        slot_display = slot_dt.astimezone(TUTOR_TIMEZONE).strftime("%d %b, %H:%M (%A)")
        slot_buttons.append([KeyboardButton(text=slot_display)])
        shown_slots_data_for_fsm[slot_display] = slot_dt.isoformat()

    if not slot_buttons:
        error_forming_slots = "Не удалось сформировать список слотов. Попробуйте снова."
        await message.answer(error_forming_slots)
        await update_fsm_and_file_history(user_id, state, "assistant", error_forming_slots) # ИСТОРИЯ
        return

    slots_choice_text = "Вот доступные слоты для записи (указано московское время). Выберите удобный:"
    await message.answer(
        slots_choice_text,
        reply_markup=ReplyKeyboardMarkup(keyboard=slot_buttons, resize_keyboard=True, one_time_keyboard=True)
    )
    await update_fsm_and_file_history(user_id, state, "assistant", slots_choice_text) # ИСТОРИЯ

    await state.set_state(UserInteraction.awaiting_time_choice)
    await state.update_data(shown_slots=shown_slots_data_for_fsm)


@router.message(UserInteraction.awaiting_purpose, F.text == "Нет, спасибо")
async def decline_slots(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    await update_fsm_and_file_history(user_id, state, "user", message.text if message.text else "") # ИСТОРИЯ

    response_text = ("Хорошо. Если передумаете, вы всегда можете снова написать мне. "
                     "Есть ли что-то еще, с чем я могу помочь?")
    await message.answer(response_text, reply_markup=ReplyKeyboardRemove())
    await update_fsm_and_file_history(user_id, state, "assistant", response_text) # ИСТОРИЯ
    await state.clear()


@router.message(UserInteraction.awaiting_time_choice, F.text)
async def process_time_choice(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    chosen_slot_display = message.text
    await update_fsm_and_file_history(user_id, state, "user", chosen_slot_display if chosen_slot_display else "") # ИСТОРИЯ

    user_data = await state.get_data()
    shown_slots_map = user_data.get('shown_slots', {})

    if chosen_slot_display not in shown_slots_map:
        error_text = "Пожалуйста, выберите один из предложенных слотов с помощью кнопок."
        await message.answer(error_text)
        await update_fsm_and_file_history(user_id, state, "assistant", error_text) # ИСТОРИЯ

        slot_buttons = [[KeyboardButton(text=display_text)] for display_text in shown_slots_map.keys()]
        if slot_buttons:
            retry_text = "Вот доступные слоты:"
            await message.answer(
                retry_text,
                reply_markup=ReplyKeyboardMarkup(keyboard=slot_buttons, resize_keyboard=True, one_time_keyboard=True)
            )
            # Не логируем повторный вывод кнопок как отдельный ответ ассистента, т.к. это часть обработки ошибки
        return

    chosen_slot_iso = shown_slots_map[chosen_slot_display]
    await state.update_data(chosen_slot_iso=chosen_slot_iso, chosen_slot_display=chosen_slot_display)

    prompt_contact_text = (f"Вы выбрали: {chosen_slot_display}.\n"
                           "Теперь, пожалуйста, напишите ваше имя и номер телефона для связи (например: Иван, +79001234567).")
    await message.answer(prompt_contact_text, reply_markup=ReplyKeyboardRemove())
    await update_fsm_and_file_history(user_id, state, "assistant", prompt_contact_text) # ИСТОРИЯ
    await state.set_state(UserInteraction.awaiting_contact_info)

# --- Этап 3: Получение контактных данных ---
@router.message(UserInteraction.awaiting_contact_info, F.text)
async def process_contact_info(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    contact_info = message.text
    await update_fsm_and_file_history(user_id, state, "user", contact_info if contact_info else "") # ИСТОРИЯ

    parts = contact_info.split(',') # type: ignore
    name = parts[0].strip()
    phone = parts[1].strip() if len(parts) > 1 else "Не указан"

    await state.update_data(name=name, phone=phone)
    user_data = await state.get_data()

    confirmation_text = (
        f"Давайте все проверим:\n"
        f"- Имя: {name}\n"
        f"- Телефон: {phone}\n"
        f"- Дата и время: {user_data.get('chosen_slot_display')}\n"
        f"- Цель занятия: {user_data.get('purpose', 'не указана')}\n"
        f"- Длительность: 60 минут\n"
        f"- Стоимость: 1000-1500₽/час (уточняется репетитором в зависимости от цели)\n\n"
        "Все верно?"
    )
    await message.answer(confirmation_text, reply_markup=ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Да, все верно")],
            [KeyboardButton(text="Нет, нужно изменить")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    ))
    await update_fsm_and_file_history(user_id, state, "assistant", confirmation_text) # ИСТОРИЯ
    await state.set_state(UserInteraction.awaiting_confirmation)

# --- Этап 4: Подтверждение и создание события ---
@router.message(UserInteraction.awaiting_confirmation, F.text == "Да, все верно")
async def confirm_booking(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id # type: ignore
    await update_fsm_and_file_history(user_id, state, "user", message.text if message.text else "") # ИСТОРИЯ

    user_data = await state.get_data()
    start_datetime_iso = user_data.get('chosen_slot_iso')
    start_datetime_obj = datetime.fromisoformat(start_datetime_iso)
    end_datetime_obj = start_datetime_obj + timedelta(hours=1)

    event_summary = f"{user_data.get('name', 'Имя не указано')} ({user_data.get('phone', 'Телефон не указан')})"
    event_description = (
        f"Цель: {user_data.get('purpose', 'не указана')}. "
        f"Запись через Telegram-бота. User ID: {user_data.get('user_id')}"
    )

    event_to_create = EventCreate(
        summary=event_summary,
        description=event_description,
        start_datetime=start_datetime_obj.isoformat(),
        end_datetime=end_datetime_obj.isoformat(),
        timezone=TUTOR_TIMEZONE.zone
    )

    booking_process_text = "Записываю вас... Пожалуйста, подождите."
    await message.answer(booking_process_text, reply_markup=ReplyKeyboardRemove())
    await update_fsm_and_file_history(user_id, state, "assistant", booking_process_text) # ИСТОРИЯ

    created_event = create_calendar_event(event_to_create)
    json_output_for_system = None # Инициализируем

    if created_event and created_event.get('id'):
        final_message_text = (
            f"Отлично! Вы успешно записаны на занятие.\n"
            f"Детали:\n"
            f"- Имя: {user_data.get('name')}\n"
            f"- Телефон: {user_data.get('phone')}\n"
            f"- Когда: {user_data.get('chosen_slot_display')}\n"
            f"- Ссылка на событие в календаре: {created_event.get('htmlLink')}\n\n"
            "Репетитор свяжется с вами для подтверждения или уточнения деталей, если это потребуется."
        )
        await message.answer(final_message_text)

        json_output_for_system = {
            "action": "create",
            "lesson": {
                "name": user_data.get('name'),
                "phone": user_data.get('phone'),
                "start_datetime": start_datetime_obj.strftime("%Y-%m-%dT%H:%M:%S"),
                "end_datetime": end_datetime_obj.strftime("%Y-%m-%dT%H:%M:%S"),
                "calendar_event_id": created_event.get('id'),
                "calendar_event_link": created_event.get('htmlLink')
            }
        }
        await update_fsm_and_file_history(user_id, state, "assistant", final_message_text, action_details=json_output_for_system) # ИСТОРИЯ с JSON

        if ADMIN_TG_ID:
            try:
                await bot.send_message(ADMIN_TG_ID, f"Новая запись через бота:\n{json.dumps(json_output_for_system, indent=2, ensure_ascii=False)}")
            except Exception as e:
                print(f"Error sending admin notification: {e}")
    else:
        error_booking_text = ("К сожалению, произошла ошибка при создании записи в календаре. "
                                 "Пожалуйста, попробуйте еще раз позже или свяжитесь с репетитором напрямую.")
        await message.answer(error_booking_text)
        await update_fsm_and_file_history(user_id, state, "assistant", error_booking_text) # ИСТОРИЯ

        if ADMIN_TG_ID:
            try:
                await bot.send_message(ADMIN_TG_ID, f"Ошибка создания записи для {user_data.get('name')}, {user_data.get('chosen_slot_display')}")
            except Exception as e:
                print(f"Error sending admin error notification: {e}")
    await state.clear()

@router.message(UserInteraction.awaiting_confirmation, F.text == "Нет, нужно изменить")
async def change_booking_details(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    await update_fsm_and_file_history(user_id, state, "user", message.text if message.text else "") # ИСТОРИЯ

    response_text = ("Хорошо. Давайте начнем процесс записи заново, чтобы все исправить.\n"
                     "Чтобы начать запись заново, используйте команду /book или /start.")
    await message.answer(response_text, reply_markup=ReplyKeyboardRemove())
    await update_fsm_and_file_history(user_id, state, "assistant", response_text) # ИСТОРИЯ
    await state.clear()

@router.message(Command("book"))
async def cmd_book(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    await state.clear()
    # Загружаем историю, чтобы она была в FSM, даже если пользователь сразу пишет /book
    dialog_history = load_history(user_id)
    await state.update_data(user_id=user_id, dialog_history=dialog_history)

    await update_fsm_and_file_history(user_id, state, "user", message.text if message.text else "/book") # ИСТОРИЯ

    greeting_text = (
        "Вы хотите записаться на занятие. Отлично!\n"
        "Скажите, пожалуйста, какова цель вашего обращения? "
        "Например: подготовка к ЕГЭ, ОГЭ, ВПР, помощь со школьной программой, и т.д."
    )
    await message.answer(greeting_text)
    await update_fsm_and_file_history(user_id, state, "assistant", greeting_text) # ИСТОРИЯ
    await state.set_state(UserInteraction.awaiting_purpose)

@router.message(Command("available_slots"))
async def cmd_available_slots(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    # При командах тоже желательно обновить историю FSM из файла, если команда вызвана вне активного диалога
    current_fsm_data = await state.get_data()
    if 'dialog_history' not in current_fsm_data or not current_fsm_data['dialog_history']: # Если истории нет в FSM или она пуста
        dialog_history = load_history(user_id)
        await state.update_data(dialog_history=dialog_history)
    if 'user_id' not in current_fsm_data: # также user_id
        await state.update_data(user_id=user_id)


    await update_fsm_and_file_history(user_id, state, "user", message.text if message.text else "/available_slots") # ИСТОРИЯ

    search_slots_text = "Ищу свободные слоты на ближайшие 7 дней..."
    await message.answer(search_slots_text, reply_markup=ReplyKeyboardRemove())
    await update_fsm_and_file_history(user_id, state, "assistant", search_slots_text) # ИСТОРИЯ

    try:
        available_slots_dt = get_available_slots(days=7)
    except Exception as e:
        error_text = "Произошла ошибка при получении слотов. Попробуйте позже или напишите репетитору."
        await message.answer(error_text)
        await update_fsm_and_file_history(user_id, state, "assistant", error_text) # ИСТОРИЯ
        return

    if not available_slots_dt:
        no_slots_msg = ("К сожалению, на ближайшие 7 дней свободных слотов нет. "
                       "Вы можете проверить позже или написать репетитору напрямую для уточнения возможных вариантов.")
        await message.answer(no_slots_msg)
        await update_fsm_and_file_history(user_id, state, "assistant", no_slots_msg) # ИСТОРИЯ
        return

    slots_text_list = [s.astimezone(TUTOR_TIMEZONE).strftime("• %d %b, %H:%M (%A)") for s in available_slots_dt]

    if not slots_text_list:
        error_forming_list = "Не удалось сформировать список слотов. Попробуйте снова."
        await message.answer(error_forming_list)
        await update_fsm_and_file_history(user_id, state, "assistant", error_forming_list) # ИСТОРИЯ
        return

    response_text = "Вот доступные слоты для записи (московское время):\n\n" + "\n".join(slots_text_list)
    response_text += "\n\nЧтобы записаться, используйте команду /book и укажите один из этих слотов, когда я спрошу."

    await message.answer(response_text)
    await update_fsm_and_file_history(user_id, state, "assistant", response_text) # ИСТОРИЯ
