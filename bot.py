#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import asyncio
import requests
import re
import pandas as pd
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import BOT_TOKEN, MAX_PAGES, MAX_VACANCIES, CITIES, DEFAULT_CITY, USER_AGENT

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния для обработки поиска
user_states = {}


def get_city_keyboard():
    """Создает клавиатуру с выбором города"""
    keyboard = InlineKeyboardBuilder()

    # Добавляем кнопки для каждого города
    for city_code, city_name in CITIES.items():
        keyboard.add(InlineKeyboardButton(
            text=city_name,
            callback_data=f"city_{city_code}"
        ))

    keyboard.adjust(2)  # 2 кнопки в ряд
    return keyboard.as_markup()


def get_main_menu():
    """Создает основное меню"""
    main_menu = ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[
            [KeyboardButton(text="🔍 Новый поиск")]
        ]
    )
    return main_menu


def create_progress_bar(percentage, width=20):
    """Создает визуальный прогресс-бар"""
    filled = int(width * percentage / 100)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return f"[{bar}] {percentage}%"


async def update_progress(message, current, total, status_msg=None):
    """Обновляет сообщение с прогресс-баром"""
    percentage = min(100, int((current / total) * 100))

    # Обновляем только каждые 5% для уменьшения количества запросов к API
    if status_msg and current % max(1, total // 20) == 0 or current == total:
        try:
            progress_bar = create_progress_bar(percentage)
            await status_msg.edit_text(
                f"🔄 Обработка вакансий...\n{progress_bar}\n"
                f"Обработано: {current}/{total}"
            )
        except Exception as e:
            print(f"Ошибка обновления прогресса: {e}")

    return percentage


def get_vacancy_urls(query, pages, area):
    """Получает список URL вакансий с сайта HH.ru"""
    urls = []
    headers = {"User-Agent": USER_AGENT}

    for n in range(pages):
        # Исправлено: убрана лишняя скобка в параметре text
        url = f"https://hh.ru/search/vacancy?text={query}&area={area}&page={n}"
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Проверка на наличие результатов
            if "По запросу «" in response.text and "ничего не найдено" in response.text:
                return urls, "not_found"

            vacancy_links = soup.find_all('a', {'data-qa': 'serp-item__title'})

            for link in vacancy_links:
                full_url = link['href']
                # Удаляем параметры после знака вопроса
                clean_url = full_url.split('?')[0]
                if "hh.ru/vacancy/" in clean_url:
                    urls.append(clean_url)

        except Exception as e:
            return urls, f"error: {str(e)}"

    return urls, "success"


def process_vacancy(url):
    """Обрабатывает одну вакансию и возвращает данные"""
    try:
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        html_content = response.text

        soup = BeautifulSoup(html_content, 'html.parser')

        # Название вакансии
        h1 = soup.find('h1', class_='bloko-header-section-1')
        title = h1.get_text(strip=True) if h1 else "Не указано"

        # Компания
        company_match = re.search(r'"hiringOrganization".*?"name"\s*:\s*"([^"]+)"', html_content)
        company = company_match.group(1) if company_match else "Не указана"

        # Адрес
        address_match = re.search(r'"displayName"\s*:\s*"([^"]+)"', html_content)
        address = address_match.group(1) if address_match else "Не указан"

        # Зарплата
        salary_match = re.search(r'"compensation"\s*:\s*\{[^}]*"to"\s*:\s*(\d+)', html_content)
        if not salary_match:
            salary_match = re.search(r'"salary"\s*:\s*\{[^}]*"to"\s*:\s*(\d+)', html_content)

        if salary_match:
            salary_to = f"до {int(salary_match.group(1)):,} ₽"
            # Тип выплаты
            gross_match = re.search(r'"gross"\s*:\s*(true|false)', html_content)
            tax = "до вычета налогов" if gross_match and gross_match.group(1) == "true" else "на руки"

            return {
                "Название вакансии": title,
                "Компания": company,
                "Адрес": address,
                "Зарплата": salary_to,
                "Выдача": tax,
                "Ссылка": url
            }
        return None

    except Exception:
        return None


async def parse_vacancies(query, pages, area, message):
    """Асинхронный парсинг вакансий с многопоточностью и прогресс-баром"""
    await message.answer(f"🔍 Начинаю поиск по запросу '{query}' на {pages} страницах...")

    # Получаем список URL
    urls, status = await asyncio.get_event_loop().run_in_executor(
        None, lambda: get_vacancy_urls(query, pages, area)
    )

    if status == "not_found":
        await message.answer("❌ По вашему запросу ничего не найдено. Попробуйте изменить запрос.")
        return None
    elif status.startswith("error"):
        await message.answer(f"⚠️ Произошла ошибка при получении списка вакансий: {status[6:]}")
        return None

    if not urls:
        await message.answer("❌ Не удалось найти вакансии по вашему запросу.")
        return None

    # Ограничиваем количество обрабатываемых вакансий
    urls = urls[:MAX_VACANCIES]

    status_msg = await message.answer("🔄 Подготовка к обработке...")

    # Многопоточная обработка
    data = []
    processed_count = 0
    skipped_count = 0

    # Отправляем начальный прогресс-бар
    await update_progress(message, 0, len(urls), status_msg)

    with ThreadPoolExecutor(max_workers=min(10, len(urls))) as executor:
        future_to_url = {executor.submit(process_vacancy, url): url for url in urls}

        for i, future in enumerate(as_completed(future_to_url), 1):
            result = future.result()
            if result:
                data.append(result)
                processed_count += 1
            else:
                skipped_count += 1

            # Обновляем прогресс
            await update_progress(message, i, len(urls), status_msg)

    # Завершаем прогресс
    await status_msg.edit_text("✅ Обработка завершена!")

    if not data:
        await message.answer("❌ Не найдено ни одной вакансии с указанной зарплатой.")
        return None

    await message.answer(f"📊 Найдено: {len(urls)} | Обработано: {processed_count} | Пропущено: {skipped_count}")
    return data


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await message.answer(
        "Добро пожаловать в бота для поиска вакансий на HH.ru!\n\n"
        "Я помогу вам найти подходящие вакансии и собрать информацию о них.\n\n"
        f"Максимальное количество страниц для поиска: {MAX_PAGES}\n"
        f"Максимальное количество обрабатываемых вакансий: {MAX_VACANCIES}\n\n"
        "Используйте меню ниже или отправьте команду /search <запрос> [количество_страниц]",
        reply_markup=get_main_menu()
    )


@dp.message(lambda message: message.text == "🔍 Новый поиск")
async def new_search(message: types.Message):
    """Запуск нового поиска"""
    await message.answer(
        "Введите запрос для поиска вакансий.\n"
        "Пример: программист python\n\n"
        "Вы также можете указать количество страниц (максимум 5):\n"
        "пример: программист python 3"
    )
    user_states[message.chat.id] = {"state": "waiting_query"}


@dp.message(Command("search"))
async def cmd_search(message: types.Message):
    """Обработчик команды /search"""
    args = message.text.split()[1:]
    if not args:
        await message.answer("Введите запрос после команды /search\nПример: /search программист python 2")
        return

    query = args[0]
    pages = 1

    if len(args) > 1:
        try:
            pages = min(int(args[1]), MAX_PAGES)
        except ValueError:
            query = " ".join(args)

    user_states[message.chat.id] = {
        "state": "processing",
        "query": query,
        "pages": pages,
        "city": DEFAULT_CITY
    }

    # Сразу запрашиваем город
    await message.answer(
        "📍 Выберите город для поиска:",
        reply_markup=get_city_keyboard()
    )


@dp.callback_query(lambda c: c.data.startswith('city_'))
async def process_city(callback_query: types.CallbackQuery):
    """Обработка выбора города"""
    city_code = callback_query.data.split('_')[1]
    chat_id = callback_query.message.chat.id

    if chat_id in user_states and "query" in user_states[chat_id]:
        user_states[chat_id]["city"] = city_code
        query = user_states[chat_id]["query"]
        pages = user_states[chat_id]["pages"]

        # Удаляем сообщение с выбором города
        await callback_query.message.delete()

        # Отправляем подтверждение выбора города
        await callback_query.message.answer(
            f"🌆 Город выбран: {CITIES.get(city_code, 'Неизвестный город')}\n"
            f"🔍 Начинаем поиск по запросу '{query}' на {pages} страницах..."
        )

        # Запускаем поиск
        await process_search(callback_query.message, query, pages, city_code)
    else:
        await callback_query.answer("Сессия поиска устарела. Начните новый поиск.", show_alert=True)


async def process_search(message, query, pages, area):
    """Обработка поискового запроса"""
    try:
        data = await parse_vacancies(query, pages, area, message)
        if not data:
            return

        # Создаем DataFrame
        df = pd.DataFrame(data)

        # Сохраняем в CSV
        csv_file = f"vacancies_{message.chat.id}.csv"
        df.to_csv(csv_file, index=False, encoding='utf-8-sig')

        # Сохраняем в Excel
        excel_file = f"vacancies_{message.chat.id}.xlsx"
        df.to_excel(excel_file, index=False)

        # Отправляем файлы
        await message.answer("📁 Готово! Отправляю результаты...")

        # Отправляем CSV
        await message.answer_document(FSInputFile(csv_file), caption="Результаты поиска в формате CSV")

        # Отправляем Excel
        await message.answer_document(FSInputFile(excel_file), caption="Результаты поиска в формате Excel")

        # Удаляем временные файлы
        os.remove(csv_file)
        os.remove(excel_file)

        # Предлагаем новые действия
        await message.answer("Поиск завершен! Что дальше?", reply_markup=get_main_menu())

    except Exception as e:
        await message.answer(f"❌ Произошла ошибка: {str(e)}")
    finally:
        if message.chat.id in user_states:
            del user_states[message.chat.id]


@dp.message()
async def handle_message(message: types.Message):
    """Обработка текстовых сообщений"""
    chat_id = message.chat.id

    if chat_id in user_states and user_states[chat_id]["state"] == "waiting_query":
        # Обработка запроса
        parts = message.text.split()
        query = parts[0]
        pages = 1

        if len(parts) > 1:
            try:
                pages = min(int(parts[-1]), MAX_PAGES)
                query = " ".join(parts[:-1])
            except ValueError:
                query = message.text

        user_states[chat_id] = {
            "state": "waiting_city",
            "query": query,
            "pages": pages
        }

        await message.answer(
            "📍 Выберите город для поиска:",
            reply_markup=get_city_keyboard()
        )
    else:
        await message.answer(
            "Я бот для поиска вакансий на HH.ru.\n"
            "Нажмите кнопку 'Новый поиск' или используйте команду /search",
            reply_markup=get_main_menu()
        )


async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())