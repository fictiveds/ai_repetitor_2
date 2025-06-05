import os
import requests
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from config import OPENROUTER_API_KEY, BOT_TOKEN # BOT_TOKEN может быть нужен для идентификации или User-Agent
from history_manager import MAX_HISTORY_LENGTH # Чтобы согласовать объем передаваемой истории

# URL API OpenRouter
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Загрузка системного промпта
SYSTEM_PROMPT_FILE = "system_prompt.txt"
SYSTEM_PROMPT = ""

if os.path.exists(SYSTEM_PROMPT_FILE):
    with open(SYSTEM_PROMPT_FILE, 'r', encoding='utf-8') as f:
        SYSTEM_PROMPT = f.read().strip()
else:
    # Фолбэк, если файл не найден (хотя он должен быть создан на первом шаге)
    SYSTEM_PROMPT = "Вы — дружелюбный AI-чатбот по имени Александр, помощник репетитора."
    print(f"ПРЕДУПРЕЖДЕНИЕ: Файл системного промпта {SYSTEM_PROMPT_FILE} не найден. Используется промпт по умолчанию.")

def get_llm_response(
    user_id: int, # Для возможного логирования или специфичных настроек пользователя в будущем
    dialog_history: List[Dict[str, Any]],
    user_input: str, # Последнее сообщение пользователя
    model: str = "google/gemini-2.5-flash-preview-05-20", # Модель по умолчанию, можно изменить
    temperature: float = 0.7,
    max_tokens: int = 1000,
    # Дополнительные параметры, специфичные для OpenRouter или модели, могут быть добавлены сюда
) -> Optional[str]:
    """
    Отправляет запрос к API OpenRouter и возвращает ответ модели.
    `dialog_history` должна быть списком словарей вида {"role": "user/assistant", "content": "text"}
    `user_input` - это текущее сообщение от пользователя, которое еще не добавлено в `dialog_history` для отправки.
    """
    if not OPENROUTER_API_KEY:
        print("Ошибка: OPENROUTER_API_KEY не установлен.")
        return "Извините, я сейчас не могу обработать ваш запрос (проблема с конфигурацией)."

    # Подготовка истории для LLM
    # Системный промпт всегда первый
    # Заменяем плейсхолдер {{ $now }} на текущую дату и время
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z")
    processed_system_prompt = SYSTEM_PROMPT.replace("{{ $now }}", current_time_str)

    messages_for_llm = [{"role": "system", "content": processed_system_prompt}]

    # Добавляем историю диалога, убедившись, что она не слишком длинная
    # MAX_HISTORY_LENGTH из history_manager относится к количеству сообщений (пар запрос-ответ)
    # Для LLM это может быть чуть иначе, но пока будем ориентироваться на это.
    # OpenRouter может иметь свои ограничения на количество токенов в запросе.

    # Берем последние N сообщений из истории (без системного, он уже добавлен)
    # Каждое сообщение в dialog_history это один элемент списка.
    # Если MAX_HISTORY_LENGTH = 50, то это 25 пар user/assistant
    history_to_send = dialog_history[-(MAX_HISTORY_LENGTH -1):] if dialog_history else []

    for entry in history_to_send:
        # Убедимся, что передаем только 'role' и 'content'
        # Исключаем 'timestamp' и 'action_details'
        if 'role' in entry and 'content' in entry:
            messages_for_llm.append({"role": entry["role"], "content": entry["content"]})

    # Добавляем текущий ввод пользователя
    messages_for_llm.append({"role": "user", "content": user_input})

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        # "HTTP-Referer": f"https://your-app-name.com", # Заменить на ваш сайт или имя приложения
        # "X-Title": "TutorBot Telegram", # Заменить на имя вашего приложения
    }
    if BOT_TOKEN: # Для примера, как можно использовать токен бота
         headers["User-Agent"] = f"TelegramBot/{BOT_TOKEN[:10]} (TutorBot)"


    data = {
        "model": model,
        "messages": messages_for_llm,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # "stream": False, # Для потоковой передачи, если потребуется
    }

    response_obj = None # Initialize response_obj to None, use a different name from the import
    try:
        # print(f"Отправка запроса в OpenRouter: {json.dumps(data, ensure_ascii=False, indent=2)}") # Для отладки
        response_obj = requests.post(OPENROUTER_API_URL, headers=headers, json=data, timeout=30) # Таймаут 30 сек
        response_obj.raise_for_status()  # Вызовет исключение для HTTP ошибок 4xx/5xx

        response_json = response_obj.json()
        # print(f"Ответ от OpenRouter: {json.dumps(response_json, ensure_ascii=False, indent=2)}") # Для отладки

        if response_json.get("choices") and len(response_json["choices"]) > 0:
            assistant_response = response_json["choices"][0]["message"]["content"]
            return assistant_response.strip()
        else:
            print(f"Ошибка: Неожиданный формат ответа от OpenRouter: {response_json}")
            # Попытка извлечь ошибку из ответа, если она есть
            if response_json.get("error"):
                return f"Ошибка от LLM: {response_json['error'].get('message', 'Неизвестная ошибка LLM')}"
            return "Не удалось получить корректный ответ от языковой модели."

    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP ошибка при обращении к OpenRouter: {http_err}")
        if response_obj is not None:
            print(f"Тело ответа (если есть): {response_obj.text}")
            return f"Произошла сетевая ошибка при обращении к сервису ({response_obj.status_code}). Попробуйте позже."
        else:
            return f"Произошла сетевая ошибка при обращении к сервису. Попробуйте позже."
    except requests.exceptions.RequestException as req_err:
        print(f"Ошибка подключения к OpenRouter: {req_err}")
        return "Проблема с подключением к сервису языковой модели. Попробуйте позже."
    except Exception as e:
        print(f"Непредвиденная ошибка при работе с LLM: {e}")
        return "Произошла внутренняя ошибка при обработке вашего запроса."

if __name__ == '__main__':
    # Пример использования (требует установленного OPENROUTER_API_KEY в .env)
    if not OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY не найден в переменных окружения. Тест не может быть выполнен.")
    else:
        print(f"Системный промпт загружен:\n---\n{SYSTEM_PROMPT[:200]}...\n---")

        test_user_id = 123
        # Пример истории диалога
        sample_history = [
            {"role": "user", "content": "Привет!"},
            {"role": "assistant", "content": "Здравствуйте! Чем могу помочь?"},
            {"role": "user", "content": "Хочу записаться на занятие по физике."},
            {"role": "assistant", "content": "Отлично! Какова цель вашего обращения? Например: подготовка к ЕГЭ, ОГЭ, ВПР, помощь со школьной программой, и т.д."}
        ]

        # Последний ввод пользователя
        current_input = "Подготовка к ЕГЭ."

        print(f"\nОтправка запроса для пользователя {test_user_id} с вводом: '{current_input}'")

        llm_response_text = get_llm_response(test_user_id, sample_history, current_input) # Renamed response to llm_response_text

        if llm_response_text:
            print(f"\nОтвет от LLM:\n{llm_response_text}")
        else:
            print("\nНе удалось получить ответ от LLM.")

        print("\n--- Тест с пустым вводом и историей (должен вернуть что-то осмысленное или ошибку) ---")
        response_empty = get_llm_response(test_user_id, [], "Привет")
        if response_empty:
            print(f"\nОтвет от LLM на пустую историю:\n{response_empty}")
        else:
            print("\nНе удалось получить ответ от LLM на пустую историю.")

        # Очистка тестовой истории, если она создавалась history_manager'ом
        # from history_manager import clear_history
        # clear_history(test_user_id)
