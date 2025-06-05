from aiogram.fsm.state import State, StatesGroup

class UserInteraction(StatesGroup):
    awaiting_purpose = State()      # Ожидание цели обращения
    awaiting_time_choice = State()  # Ожидание выбора времени (после показа слотов)
    awaiting_contact_info = State() # Ожидание контактной информации (имя, телефон)
    awaiting_confirmation = State() # Ожидание подтверждения записи (да/нет)

    awaiting_cancel_reason = State() # Ожидание причины отмены (если нужно)
    awaiting_cancel_slot_choice = State() # Ожидание выбора слота для отмены
    awaiting_cancel_confirmation = State() # Ожидание подтверждения отмены

    # Общее состояние для обработки сообщений через LLM, когда нет активного FSM
    general_conversation = State()
