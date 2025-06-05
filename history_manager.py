import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
import asyncio # Added for the test function

HISTORY_DIR = "user_histories"
MAX_HISTORY_LENGTH = 50 # Максимальное количество сообщений в истории для одного пользователя (чтобы файлы не были слишком большими)

# Убедимся, что директория для историй существует
if not os.path.exists(HISTORY_DIR):
    os.makedirs(HISTORY_DIR)

def get_history_filepath(user_id: int) -> str:
    """Возвращает путь к файлу истории для данного пользователя."""
    return os.path.join(HISTORY_DIR, f"history_{user_id}.json")

def load_history(user_id: int) -> List[Dict[str, Any]]:
    """Загружает историю сообщений для пользователя."""
    filepath = get_history_filepath(user_id)
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                history = json.load(f)
            # Ограничиваем длину истории при загрузке, если она превышает максимум
            if len(history) > MAX_HISTORY_LENGTH:
                history = history[-MAX_HISTORY_LENGTH:]
            return history
        except json.JSONDecodeError:
            # Если файл поврежден, возвращаем пустую историю
            return []
        except Exception:
            # Другие возможные ошибки чтения файла
            return []
    return []

def save_history(user_id: int, history: List[Dict[str, Any]]):
    """Сохраняет историю сообщений для пользователя."""
    filepath = get_history_filepath(user_id)
    try:
        # Ограничиваем длину истории перед сохранением
        if len(history) > MAX_HISTORY_LENGTH:
            history_to_save = history[-MAX_HISTORY_LENGTH:]
        else:
            history_to_save = history

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(history_to_save, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # В реальном приложении здесь должно быть логирование ошибки
        print(f"Error saving history for user {user_id}: {e}")


def add_message_to_history(
    user_id: int,
    role: str,  # "user" или "assistant"
    content: str,
    action_details: Optional[Dict[str, Any]] = None # Для сохранения деталей действия (json_output_for_system)
) -> List[Dict[str, Any]]:
    """
    Добавляет новое сообщение в историю пользователя и сохраняет ее.
    Возвращает обновленную историю.
    """
    history = load_history(user_id)

    message_entry = {
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat()
    }
    if action_details:
        message_entry["action_details"] = action_details

    history.append(message_entry)

    # Ограничение длины истории (самые старые сообщения удаляются)
    if len(history) > MAX_HISTORY_LENGTH:
        history = history[-MAX_HISTORY_LENGTH:]

    save_history(user_id, history)
    return history

def clear_history(user_id: int):
    """Очищает историю для пользователя."""
    filepath = get_history_filepath(user_id)
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception as e:
            print(f"Error clearing history for user {user_id}: {e}")

# --- Интеграция с FSMContext ---
async def get_dialog_history_from_fsm(state_data: Dict[str, Any], user_id: int) -> List[Dict[str, Any]]:
    """
    Получает историю диалога. Сначала пытается из FSM, потом из файла.
    Это позволяет держать актуальную историю в FSM во время активного диалога.
    """
    fsm_history = state_data.get('dialog_history')
    if fsm_history is not None and isinstance(fsm_history, list):
        return fsm_history
    return load_history(user_id)

async def update_fsm_and_file_history(
    user_id: int,
    state: Optional[Any], # FSMContext object
    role: str,
    content: str,
    action_details: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Обновляет историю в FSM и сохраняет ее в файл.
    Если state is None, обновляет только файл.
    """
    current_history = []
    if state:
        user_data = await state.get_data()
        current_history = await get_dialog_history_from_fsm(user_data, user_id)
    else:
        current_history = load_history(user_id)

    message_entry = {
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat()
    }
    if action_details:
        message_entry["action_details"] = action_details

    current_history.append(message_entry)

    if len(current_history) > MAX_HISTORY_LENGTH:
        current_history = current_history[-MAX_HISTORY_LENGTH:]

    if state:
        await state.update_data(dialog_history=current_history)

    save_history(user_id, current_history) # Всегда сохраняем в файл для персистентности
    return current_history


if __name__ == '__main__':
    # Пример использования
    test_user_id = 12345

    print(f"Текущая история для {test_user_id}: {load_history(test_user_id)}")

    add_message_to_history(test_user_id, "user", "Привет, хочу записаться")
    add_message_to_history(test_user_id, "assistant", "Здравствуйте! На какое время?")

    print(f"Обновленная история: {load_history(test_user_id)}")

    # Имитация работы с FSM
    class MockState:
        def __init__(self):
            self.data = {}
        async def get_data(self):
            return self.data
        async def update_data(self, **kwargs):
            self.data.update(kwargs)
            return self.data
        async def clear(self):
            self.data = {}

    async def run_fsm_test():
        mock_state = MockState()
        # Начальная загрузка в FSM (например, при /start)
        initial_history = load_history(test_user_id)
        await mock_state.update_data(dialog_history=initial_history, user_id=test_user_id)
        print(f"История в FSM после загрузки: {(await mock_state.get_data()).get('dialog_history')}")

        # Добавление сообщения через новую функцию
        await update_fsm_and_file_history(
            user_id=test_user_id,
            state=mock_state,
            role="user",
            content="Хочу отменить занятие во вторник."
        )
        print(f"История в FSM после добавления: {(await mock_state.get_data()).get('dialog_history')}")
        print(f"История в файле после добавления: {load_history(test_user_id)}")

    # asyncio.run(run_fsm_test()) # Закомментировано, т.к. требует asyncio контекста
    # Примечание: для запуска этого теста из командной строки, нужно раскомментировать
    # строку выше и обернуть вызов в if __name__ == "__main__": `asyncio.run(run_fsm_test())`
    # или использовать `python -m asyncio history_manager.py` (если модуль структурирован для этого)

    # clear_history(test_user_id)
    # print(f"История после очистки: {load_history(test_user_id)}")
