from aiogram import Router, F, Bot
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
import json

from states import UserInteraction
from calendar_integration import (
    get_booked_slots_by_user,
    delete_calendar_event,
    TUTOR_TIMEZONE
)
from config import ADMIN_TG_ID
from history_manager import update_fsm_and_file_history, load_history

router = Router()

@router.message(Command("cancel_lesson"))
async def cmd_cancel_lesson(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    await state.clear()
    dialog_history = load_history(user_id)
    await state.update_data(user_id=user_id, dialog_history=dialog_history)

    await update_fsm_and_file_history(user_id, state, "user", message.text if message.text else "/cancel_lesson") # ИСТОРИЯ

    prompt_text = ("Вы хотите отменить занятие. "
                   "Пожалуйста, напишите ваше имя и номер телефона, которые вы указывали при записи "
                   "(например: Иван, +79001234567), чтобы я мог найти ваши записи.")
    await message.answer(prompt_text, reply_markup=ReplyKeyboardRemove())
    await update_fsm_and_file_history(user_id, state, "assistant", prompt_text) # ИСТОРИЯ
    await state.set_state(UserInteraction.awaiting_cancel_details)

@router.message(UserInteraction.awaiting_cancel_details, F.text)
async def process_cancellation_details(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    contact_info = message.text
    await update_fsm_and_file_history(user_id, state, "user", contact_info if contact_info else "") # ИСТОРИЯ

    try:
        name, phone = [part.strip() for part in contact_info.split(',')] # type: ignore
    except ValueError:
        error_text = "Пожалуйста, введите имя и телефон в формате: Имя, +7Телефон. Например: Иван, +79001234567"
        await message.answer(error_text)
        await update_fsm_and_file_history(user_id, state, "assistant", error_text) # ИСТОРИЯ
        return

    await state.update_data(cancel_name=name, cancel_phone=phone)
    searching_text = f"Ищу ваши записи для {name}, телефон {phone}..."
    await message.answer(searching_text)
    await update_fsm_and_file_history(user_id, state, "assistant", searching_text) # ИСТОРИЯ

    booked_events = get_booked_slots_by_user(name=name, phone=phone)

    if not booked_events:
        no_bookings_text = ("Не нашел активных записей на ваше имя и телефон. "
                           "Возможно, вы указали другие данные при записи, или запись была отменена ранее. "
                           "Если уверены, что запись есть, попробуйте уточнить данные или свяжитесь с репетитором.")
        await message.answer(no_bookings_text)
        await update_fsm_and_file_history(user_id, state, "assistant", no_bookings_text) # ИСТОРИЯ
        await state.clear()
        return

    event_options = {}
    keyboard_buttons = []
    for event in booked_events:
        event_id = event['id']
        summary = event.get('summary', 'Без названия')
        start_iso = event['start'].get('dateTime', event['start'].get('date'))

        try:
            # Ensure start_iso is a string before replace
            start_iso_str = str(start_iso)
            if 'T' in start_iso_str: # dateTime format
                start_dt_obj = datetime.fromisoformat(start_iso_str.replace('Z', '+00:00')).astimezone(TUTOR_TIMEZONE)
                display_time = start_dt_obj.strftime("%d %b, %H:%M (%A)")
            else: # date format
                start_dt_obj = datetime.strptime(start_iso_str, "%Y-%m-%d").date()
                display_time = start_dt_obj.strftime("%d %b %Y (%A)")
        except ValueError:
            display_time = str(start_iso)


        option_text = f"{display_time} - {summary}"
        event_options[option_text] = {"id": event_id, "summary": summary, "start_iso": start_iso, "name": name, "phone": phone}
        keyboard_buttons.append([KeyboardButton(text=option_text)])

    if not keyboard_buttons:
        error_forming_list = "Не удалось сформировать список ваших записей для отмены. Пожалуйста, свяжитесь с репетитором."
        await message.answer(error_forming_list)
        await update_fsm_and_file_history(user_id, state, "assistant", error_forming_list) # ИСТОРИЯ
        await state.clear()
        return

    await state.update_data(event_options_for_cancel=event_options)
    prompt_choice_text = "Вот ваши предстоящие записи. Какую из них вы хотите отменить?"
    await message.answer(
        prompt_choice_text,
        reply_markup=ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True, one_time_keyboard=True)
    )
    await update_fsm_and_file_history(user_id, state, "assistant", prompt_choice_text) # ИСТОРИЯ
    await state.set_state(UserInteraction.awaiting_cancel_slot_choice)

@router.message(UserInteraction.awaiting_cancel_slot_choice, F.text)
async def process_cancel_slot_choice(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    chosen_event_text = message.text
    await update_fsm_and_file_history(user_id, state, "user", chosen_event_text if chosen_event_text else "") # ИСТОРИЯ

    user_data = await state.get_data()
    event_options = user_data.get('event_options_for_cancel', {})

    if chosen_event_text not in event_options:
        error_text = "Пожалуйста, выберите одно из предложенных занятий с помощью кнопок."
        await message.answer(error_text)
        await update_fsm_and_file_history(user_id, state, "assistant", error_text) # ИСТОРИЯ
        # Повторно показать клавиатуру
        slot_buttons = [[KeyboardButton(text=display_text)] for display_text in event_options.keys()]
        if slot_buttons:
             await message.answer("Доступные записи для отмены:", reply_markup=ReplyKeyboardMarkup(keyboard=slot_buttons, resize_keyboard=True, one_time_keyboard=True))
        return

    selected_event_details = event_options[chosen_event_text]
    await state.update_data(selected_event_to_cancel=selected_event_details)

    confirmation_text = (
        f"Вы уверены, что хотите отменить занятие: {chosen_event_text}?\n"
        f"Имя: {selected_event_details.get('name')}\n"
        f"Телефон: {selected_event_details.get('phone')}"
    )
    await message.answer(confirmation_text, reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Да, отменить это занятие")], [KeyboardButton(text="Нет, не отменять")]],
        resize_keyboard=True, one_time_keyboard=True
    ))
    await update_fsm_and_file_history(user_id, state, "assistant", confirmation_text) # ИСТОРИЯ
    await state.set_state(UserInteraction.awaiting_cancel_confirmation)

@router.message(UserInteraction.awaiting_cancel_confirmation, F.text == "Да, отменить это занятие")
async def confirm_cancellation(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id # type: ignore
    await update_fsm_and_file_history(user_id, state, "user", message.text if message.text else "") # ИСТОРИЯ

    user_data = await state.get_data()
    event_to_cancel = user_data.get('selected_event_to_cancel')

    if not event_to_cancel or not event_to_cancel.get('id'):
        error_text = "Произошла ошибка, не могу определить какое занятие отменить. Пожалуйста, начните сначала /cancel_lesson."
        await message.answer(error_text, reply_markup=ReplyKeyboardRemove())
        await update_fsm_and_file_history(user_id, state, "assistant", error_text) # ИСТОРИЯ
        await state.clear()
        return

    event_id = event_to_cancel['id']
    cancelling_text = f"Отменяю занятие {event_to_cancel.get('summary')}..."
    await message.answer(cancelling_text, reply_markup=ReplyKeyboardRemove())
    await update_fsm_and_file_history(user_id, state, "assistant", cancelling_text) # ИСТОРИЯ

    deleted_successfully = delete_calendar_event(event_id)
    json_output_for_system = None

    if deleted_successfully:
        final_message_text = f"Занятие '{event_to_cancel.get('summary')}' успешно отменено."
        await message.answer(final_message_text)

        start_iso_str = str(event_to_cancel['start_iso'])
        if 'T' in start_iso_str:
            start_datetime_obj = datetime.fromisoformat(start_iso_str.replace('Z', '+00:00'))
        else: # Date only, assume start of day in local timezone of event if possible, or UTC
            start_datetime_obj = datetime.strptime(start_iso_str, "%Y-%m-%d")
            # If it's a date-only event, it might not have a specific time,
            # for consistency, we can make it midnight in TUTOR_TIMEZONE or keep as is.
            # For now, let's assume it was stored/retrieved as a specific datetime or needs to be handled as such.
            # This part might need refinement based on how all-day events are treated vs timed events.
            # Assuming it's a timed event for calculation of end_datetime.

        end_datetime_obj = start_datetime_obj + timedelta(hours=1) # Assuming 1 hour duration

        json_output_for_system = {
            "action": "delete",
            "lesson": {
                "name": event_to_cancel.get('name'), "phone": event_to_cancel.get('phone'),
                "start_datetime": start_datetime_obj.strftime("%Y-%m-%dT%H:%M:%S"),
                "end_datetime": end_datetime_obj.strftime("%Y-%m-%dT%H:%M:%S"),
                "calendar_event_id": event_id
            }
        }
        await update_fsm_and_file_history(user_id, state, "assistant", final_message_text, action_details=json_output_for_system) # ИСТОРИЯ с JSON

        if ADMIN_TG_ID:
            try:
                await bot.send_message(ADMIN_TG_ID, f"Занятие отменено через бота:\n{json.dumps(json_output_for_system, indent=2, ensure_ascii=False)}")
            except Exception as e: print(f"Error sending admin cancel notification: {e}")
    else:
        error_cancel_text = ("Не удалось отменить занятие. Возможно, оно уже было отменено или произошла ошибка. "
                             "Пожалуйста, свяжитесь с репетитором для уточнения.")
        await message.answer(error_cancel_text)
        await update_fsm_and_file_history(user_id, state, "assistant", error_cancel_text) # ИСТОРИЯ

    await state.clear()

@router.message(UserInteraction.awaiting_cancel_confirmation, F.text == "Нет, не отменять")
async def decline_cancellation(message: Message, state: FSMContext):
    user_id = message.from_user.id # type: ignore
    await update_fsm_and_file_history(user_id, state, "user", message.text if message.text else "") # ИСТОРИЯ

    response_text = ("Хорошо, занятие не будет отменено. "
                     "Если что-то еще нужно, дайте знать.")
    await message.answer(response_text, reply_markup=ReplyKeyboardRemove())
    await update_fsm_and_file_history(user_id, state, "assistant", response_text) # ИСТОРИЯ
    await state.clear()
