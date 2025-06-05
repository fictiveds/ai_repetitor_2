from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta, time
import pytz # Для работы с часовыми поясами
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import logging

from config import GOOGLE_CALENDAR_ID, SERVICE_ACCOUNT_FILE

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Настройки Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']
CALENDAR_ID = GOOGLE_CALENDAR_ID
SERVICE_ACCOUNT_FILE_PATH = SERVICE_ACCOUNT_FILE

# Часовой пояс репетитора
TUTOR_TIMEZONE = pytz.timezone("Europe/Moscow")

class EventCreate(BaseModel):
    summary: str = Field(..., description="Название события (Имя ученика и телефон)")
    description: Optional[str] = Field(None, description="Описание события (цель занятия)")
    start_datetime: str = Field(..., description="Дата и время начала (ISO format)")
    end_datetime: str = Field(..., description="Дата и время окончания (ISO format)")
    timezone: str = Field(default=TUTOR_TIMEZONE.zone, description="Часовой пояс")
    # attendees: Optional[List[str]] = Field(None, description="Список email участников") # Пока не используется

class EventResponse(BaseModel):
    id: str
    summary: Optional[str]
    description: Optional[str]
    location: Optional[str]
    start: Dict[str, str]
    end: Dict[str, str]
    htmlLink: str
    status: str

def get_calendar_service() -> Optional[Any]:
    """Создает и возвращает сервис Google Calendar API."""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE_PATH, scopes=SCOPES
        )
        service = build('calendar', 'v3', credentials=credentials)
        logger.info("Сервис Google Calendar успешно инициализирован.")
        return service
    except Exception as e:
        logger.error(f"Ошибка инициализации Google Calendar API: {str(e)}")
        # В реальном приложении здесь можно было бы отправить уведомление администратору
        return None

def get_busy_slots(service: Any, date_start: datetime, date_end: datetime) -> List[Dict[str, datetime]]:
    """
    Получает список занятых слотов в указанном диапазоне дат.
    Возвращает список словарей с 'start' и 'end' временем каждого события.
    """
    if not service:
        return []
    try:
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=date_start.isoformat(),
            timeMax=date_end.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        busy_slots = []
        for event in events:
            start_str = event['start'].get('dateTime', event['start'].get('date'))
            end_str = event['end'].get('dateTime', event['end'].get('date'))

            # Преобразуем в datetime объекты с учетом часового пояса
            # Google API возвращает время в UTC (если есть Z) или без часового пояса (если это событие на весь день)
            if 'Z' in start_str:
                start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            else: # Предполагаем, что это дата без времени (событие на весь день) или локальное время
                start_dt = TUTOR_TIMEZONE.localize(datetime.fromisoformat(start_str))

            if 'Z' in end_str:
                end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            else:
                end_dt = TUTOR_TIMEZONE.localize(datetime.fromisoformat(end_str))

            busy_slots.append({'start': start_dt, 'end': end_dt})
        logger.info(f"Получено {len(busy_slots)} занятых слотов с {date_start.strftime('%Y-%m-%d')} по {date_end.strftime('%Y-%m-%d')}.")
        return busy_slots
    except HttpError as error:
        logger.error(f"Ошибка Google API при получении событий: {error}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при получении занятых слотов: {str(e)}")
    return []

def get_available_slots(days: int = 7) -> List[datetime]:
    """
    Возвращает список доступных слотов для записи на ближайшие `days` дней.
    Учитывает рабочее время репетитора (17:00 - 22:00 МСК) и уже занятые слоты.
    Длительность одного слота - 1 час.
    """
    service = get_calendar_service()
    if not service:
        return []

    available_slots_dt = []
    now_moscow = datetime.now(TUTOR_TIMEZONE)

    # Рабочее время репетитора
    work_start_time = time(17, 0, tzinfo=TUTOR_TIMEZONE)
    work_end_time = time(22, 0, tzinfo=TUTOR_TIMEZONE) # Последний слот начинается в 21:00

    # Получаем занятые слоты на ближайшие `days` + 1 (чтобы учесть переход через полночь)
    query_start_date = now_moscow.replace(hour=0, minute=0, second=0, microsecond=0)
    query_end_date = query_start_date + timedelta(days=days + 1)
    busy_slots = get_busy_slots(service, query_start_date, query_end_date)

    for i in range(days):
        current_day = now_moscow.date() + timedelta(days=i)

        # Проверяем слоты с 17:00 до 21:00 включительно
        for hour in range(work_start_time.hour, work_end_time.hour):
            slot_start = TUTOR_TIMEZONE.localize(datetime.combine(current_day, time(hour, 0)))
            slot_end = slot_start + timedelta(hours=1)

            # Слот должен быть в будущем
            if slot_start < now_moscow:
                continue

            # Проверяем, не занят ли слот
            is_busy = False
            for busy_slot in busy_slots:
                # Проверка пересечения временных интервалов
                busy_start_aware = busy_slot['start'].astimezone(TUTOR_TIMEZONE)
                busy_end_aware = busy_slot['end'].astimezone(TUTOR_TIMEZONE)
                if max(slot_start, busy_start_aware) < min(slot_end, busy_end_aware):
                    is_busy = True
                    break

            if not is_busy:
                available_slots_dt.append(slot_start)

    logger.info(f"Найдено {len(available_slots_dt)} свободных слотов на ближайшие {days} дней.")
    return sorted(list(set(available_slots_dt))) # Убираем дубликаты и сортируем

def create_calendar_event(event_data: EventCreate) -> Optional[Dict[str, Any]]:
    """Создает новое событие в календаре."""
    service = get_calendar_service()
    if not service:
        return None

    event_body = {
        'summary': event_data.summary,
        'description': event_data.description,
        'start': {
            'dateTime': event_data.start_datetime,
            'timeZone': event_data.timezone,
        },
        'end': {
            'dateTime': event_data.end_datetime,
            'timeZone': event_data.timezone,
        },
        # 'attendees': [{'email': email} for email in event_data.attendees] if event_data.attendees else [],
        'reminders': { # Добавляем напоминания
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': 60}, # За час
                {'method': 'popup', 'minutes': 1440}, # За сутки (24*60)
            ],
        },
    }

    try:
        created_event = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event_body,
            sendNotifications=True # Отправлять уведомления участникам (если они есть)
        ).execute()
        logger.info(f"Событие '{created_event.get('summary')}' успешно создано с ID: {created_event.get('id')}")
        return created_event
    except HttpError as error:
        logger.error(f"Ошибка Google API при создании события: {error}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при создании события: {str(e)}")
    return None

def delete_calendar_event(event_id: str) -> bool:
    """Удаляет событие из календаря по ID."""
    service = get_calendar_service()
    if not service:
        return False
    try:
        service.events().delete(
            calendarId=CALENDAR_ID,
            eventId=event_id,
            sendNotifications=True
        ).execute()
        logger.info(f"Событие с ID {event_id} успешно удалено.")
        return True
    except HttpError as error:
        if error.resp.status == 404:
            logger.warning(f"Событие с ID {event_id} не найдено для удаления.")
        else:
            logger.error(f"Ошибка Google API при удалении события {event_id}: {error}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при удалении события {event_id}: {str(e)}")
    return False

def get_event_by_id(event_id: str) -> Optional[Dict[str, Any]]:
    """Получает информацию о конкретном событии по ID."""
    service = get_calendar_service()
    if not service:
        return None
    try:
        event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
        logger.info(f"Информация о событии с ID {event_id} успешно получена.")
        return event
    except HttpError as error:
        if error.resp.status == 404:
            logger.warning(f"Событие с ID {event_id} не найдено.")
        else:
            logger.error(f"Ошибка Google API при получении события {event_id}: {error}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при получении события {event_id}: {str(e)}")
    return None

def find_event_id_by_details(start_datetime_iso: str, name: str, phone: str) -> Optional[str]:
    """
    Ищет событие по времени начала, имени и телефону в summary.
    Возвращает ID события или None, если не найдено.
    Предполагается, что имя и телефон хранятся в summary в формате "Имя (Телефон)".
    """
    service = get_calendar_service()
    if not service:
        return None

    try:
        # Преобразуем строку ISO в datetime объект
        start_dt_obj = datetime.fromisoformat(start_datetime_iso)

        # Ищем события, которые начинаются в тот же час
        time_min = start_dt_obj.isoformat()
        time_max = (start_dt_obj + timedelta(hours=1) - timedelta(seconds=1)).isoformat() # в пределах этого часа

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        summary_pattern = f"{name} ({phone})" # Ожидаемый формат summary

        for event in events:
            event_start_str = event['start'].get('dateTime')
            event_summary = event.get('summary', '')

            if event_start_str:
                event_start_dt = datetime.fromisoformat(event_start_str.replace('Z', '+00:00')).astimezone(TUTOR_TIMEZONE)
                # Сравниваем время начала с точностью до минуты
                if event_start_dt.replace(second=0, microsecond=0) == start_dt_obj.astimezone(TUTOR_TIMEZONE).replace(second=0, microsecond=0)                    and summary_pattern.lower() in event_summary.lower():
                    logger.info(f"Найдено событие для удаления: ID {event['id']}, summary: {event_summary}")
                    return event['id']

        logger.warning(f"Событие для удаления не найдено по деталям: время {start_datetime_iso}, имя {name}, телефон {phone}")
        return None
    except HttpError as error:
        logger.error(f"Ошибка Google API при поиске события для удаления: {error}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при поиске события для удаления: {str(e)}")
    return None

def get_booked_slots_by_user(name: str, phone: str, days_limit: int = 30) -> List[Dict[str, Any]]:
    """
    Получает список забронированных слотов для пользователя (по имени и телефону в summary)
    на ближайшие `days_limit` дней.
    Возвращает список словарей событий Google Calendar.
    """
    service = get_calendar_service()
    if not service:
        return []

    now_moscow = datetime.now(TUTOR_TIMEZONE)
    time_min_iso = now_moscow.isoformat()
    time_max_iso = (now_moscow + timedelta(days=days_limit)).isoformat()

    summary_pattern = f"{name} ({phone})" # Ожидаемый формат summary
    logger.info(f"Поиск событий для '{summary_pattern}' с {time_min_iso} по {time_max_iso}")

    try:
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=time_min_iso,
            timeMax=time_max_iso,
            q=summary_pattern, # Используем q для поиска по тексту в событии (включая summary)
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        user_events = []
        for event in events:
            # Дополнительно проверяем, что summary ТОЧНО соответствует,
            # так как q может дать более широкие результаты
            if summary_pattern.lower() in event.get('summary', '').lower():
                # Конвертируем время начала в datetime объект для удобства
                start_str = event['start'].get('dateTime', event['start'].get('date'))
                event_start_dt_aware = None
                if 'Z' in start_str: # UTC datetime
                    event_start_dt_aware = datetime.fromisoformat(start_str.replace('Z', '+00:00')).astimezone(TUTOR_TIMEZONE)
                elif 'T' in start_str: # Datetime with no explicit timezone (assume TUTOR_TIMEZONE)
                    try:
                        dt_naive = datetime.fromisoformat(start_str)
                        event_start_dt_aware = TUTOR_TIMEZONE.localize(dt_naive)
                    except ValueError as ve:
                        logger.warning(f"Could not parse datetime string {start_str} for event {event.get('id')}: {ve}")
                        continue # Skip this event if time is unparsable
                else: # Date only
                    try:
                        event_date_obj = datetime.strptime(start_str, "%Y-%m-%d").date()
                        # To compare with now_moscow, make it a datetime at the start of the day in TUTOR_TIMEZONE
                        event_start_dt_aware = TUTOR_TIMEZONE.localize(datetime.combine(event_date_obj, time.min))
                    except ValueError as ve:
                        logger.warning(f"Could not parse date string {start_str} for event {event.get('id')}: {ve}")
                        continue # Skip this event if date is unparsable

                # Проверяем, что событие еще не прошло (или только что началось)
                # now_moscow is already timezone-aware
                if event_start_dt_aware and event_start_dt_aware >= now_moscow - timedelta(minutes=10): # Даем 10 мин "люфта"
                    user_events.append(event)

        logger.info(f"Найдено {len(user_events)} событий для пользователя {name} ({phone}) на ближайшие {days_limit} дней.")
        return user_events
    except HttpError as error:
        logger.error(f"Ошибка Google API при поиске событий пользователя: {error}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при поиске событий пользователя: {str(e)}")
    return []

# Пример использования (для тестирования)
if __name__ == '__main__':
    print("Тестирование модуля calendar_integration...")

    # Убедитесь, что .env файл существует и SERVICE_ACCOUNT_FILE и GOOGLE_CALENDAR_ID корректно указаны
    if not SERVICE_ACCOUNT_FILE_PATH or not CALENDAR_ID:
        print("Переменные SERVICE_ACCOUNT_FILE или GOOGLE_CALENDAR_ID не установлены. Проверьте .env файл.")
    else:
        print(f"Используется файл сервисного аккаунта: {SERVICE_ACCOUNT_FILE_PATH}")
        print(f"Используется ID календаря: {CALENDAR_ID}")

        # # 1. Получение доступных слотов
        # print("\n--- Получение доступных слотов ---")
        # available = get_available_slots(days=7)
        # if available:
        #     print(f"Доступные слоты (время по МСК, {TUTOR_TIMEZONE}):")
        #     for slot in available:
        #         print(slot.strftime("%Y-%m-%d %H:%M:%S %Z%z"))
        # else:
        #     print("Нет доступных слотов или ошибка при получении.")

        # # 2. Создание тестового события (ЗАКОММЕНТИРОВАНО, чтобы не создавать мусор)
        # print("\n--- Создание тестового события ---")
        # test_event_start = (datetime.now(TUTOR_TIMEZONE) + timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
        # test_event_end = test_event_start + timedelta(hours=1)
        #
        # event_to_create = EventCreate(
        #     summary="Тестовое событие (Иван Тестов)",
        #     description="Проверка API",
        #     start_datetime=test_event_start.isoformat(),
        #     end_datetime=test_event_end.isoformat(),
        #     timezone=TUTOR_TIMEZONE.zone
        # )
        # created_event = create_calendar_event(event_to_create)
        # if created_event:
        #     print(f"Событие создано: {created_event.get('summary')}, ID: {created_event.get('id')}, Ссылка: {created_event.get('htmlLink')}")
        #     TEST_EVENT_ID = created_event.get('id')
        #
        #     # 3. Получение информации о созданном событии
        #     print("\n--- Получение информации о событии ---")
        #     if TEST_EVENT_ID:
        #         event_details = get_event_by_id(TEST_EVENT_ID)
        #         if event_details:
        #             print(f"Детали события ID {TEST_EVENT_ID}: {event_details.get('summary')}, Start: {event_details.get('start', {}).get('dateTime')}")
        #         else:
        #             print(f"Не удалось получить детали события с ID {TEST_EVENT_ID}")
        #
        #     # 4. Поиск события по деталям
        #     print("\n--- Поиск события по деталям ---")
        #     found_event_id = find_event_id_by_details(
        #         start_datetime_iso=test_event_start.isoformat(),
        #         name="Иван Тестов",
        #         phone="" # В summary мы не добавляли телефон для этого тестового события
        #     )
        #     if found_event_id:
        #         print(f"Событие найдено по деталям, ID: {found_event_id}")
        #     else:
        #         print("Событие не найдено по деталям.")
        #
        #
        #     # 5. Удаление тестового события
        #     print("\n--- Удаление тестового события ---")
        #     if TEST_EVENT_ID:
        #         if delete_calendar_event(TEST_EVENT_ID):
        #             print(f"Событие {TEST_EVENT_ID} удалено.")
        #         else:
        #             print(f"Не удалось удалить событие {TEST_EVENT_ID}.")
        # else:
        #     print("Тестовое событие не было создано, остальные тесты пропускаются.")

        # Тест получения занятых слотов
        print("\n--- Получение занятых слотов (для отладки) ---")
        debug_start_date = datetime.now(TUTOR_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        debug_end_date = debug_start_date + timedelta(days=3)
        service_instance = get_calendar_service()
        if service_instance:
            busy = get_busy_slots(service_instance, debug_start_date, debug_end_date)
            if busy:
                print(f"Занятые слоты на ближайшие 3 дня (время по МСК, {TUTOR_TIMEZONE}):")
                for slot in busy:
                    start_aware = slot['start'].astimezone(TUTOR_TIMEZONE)
                    end_aware = slot['end'].astimezone(TUTOR_TIMEZONE)
                    print(f"  Start: {start_aware.strftime('%Y-%m-%d %H:%M')} - End: {end_aware.strftime('%Y-%m-%d %H:%M')}")
            else:
                print("Нет занятых слотов в указанный период или ошибка при получении.")
        else:
            print("Не удалось инициализировать сервис календаря для теста get_busy_slots.")
