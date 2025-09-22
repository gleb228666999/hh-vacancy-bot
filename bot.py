# bot.py

import logging
import os
import requests
import pandas as pd
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes
)
from config import TELEGRAM_TOKEN, HEADERS, DEFAULT_AREA

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
PAGES, QUERY = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало диалога и запрос количества страниц"""
    await update.message.reply_text(
        "👋 Привет! Я помогу найти вакансии на HH.ru\n\n"
        "Сколько страниц парсить? (введите число)"
    )
    return PAGES

async def pages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение количества страниц и запрос поискового запроса"""
    try:
        pages = int(update.message.text)
        if pages < 1 or pages > 50:
            raise ValueError
        context.user_data['pages'] = pages
        await update.message.reply_text(
            f"✅ Отлично! Парсить {pages} страниц(ы)\n\n"
            "Введите поисковый запрос (например: 'python разработчик')"
        )
        return QUERY
    except (ValueError, TypeError):
        await update.message.reply_text(
            "❌ Ошибка! Введите число от 1 до 50\n"
            "Попробуйте снова:"
        )
        return PAGES

async def query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запуск парсинга и отправка результатов"""
    query_text = update.message.text.strip()
    pages = context.user_data['pages']

    await update.message.reply_text(
        f"🔍 Начинаю поиск по запросу '{query_text}'...\n"
        f"⏳ Парсинг {pages} страниц(ы). Это может занять 2-5 минут..."
    )

    try:
        urls = parse_vacancy_links(pages, query_text)

        if not urls:
            await update.message.reply_text(
                "❌ Не найдено ни одной вакансии. Попробуйте изменить запрос."
            )
            return ConversationHandler.END

        await update.message.reply_text(
            f"✅ Найдено {len(urls)} вакансий. Собираю детали..."
        )

        data = collect_vacancy_data(urls)

        if not data:
            await update.message.reply_text(
                "❌ Не удалось собрать данные по вакансиям."
            )
            return ConversationHandler.END

        csv_path, excel_path = save_data(data)

        with open(csv_path, 'rb') as csv:
            await update.message.reply_document(
                document=csv,
                filename="vacancies.csv",
                caption="📄 Результаты в формате CSV"
            )

        with open(excel_path, 'rb') as excel:
            await update.message.reply_document(
                document=excel,
                filename="vacancies.xlsx",
                caption="📊 Результаты в формате Excel"
            )

        os.remove(csv_path)
        os.remove(excel_path)

        await update.message.reply_text(
            "✅ Готово! Вы можете открыть файлы в Excel или таблицах.\n"
            "Хотите найти что-то ещё? Нажмите /start"
        )

    except Exception as e:
        logger.exception(e)
        await update.message.reply_text(
            f"❌ Произошла ошибка: {str(e)}\n"
            "Попробуйте позже или измените запрос."
        )

    return ConversationHandler.END

def parse_vacancy_links(pages: int, query: str) -> list:
    """Парсинг ссылок на вакансии"""
    urls = []

    for page in range(pages):
        url = (
            f"https://hh.ru/search/vacancy?"
            f"text={query}&"
            f"area={DEFAULT_AREA}&"
            f"page={page}"
        )

        try:
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            for link in soup.find_all('a', {'data-qa': 'serp-item__title'}):
                vacancy_url = link['href']
                if 'hh.ru/vacancy' in vacancy_url and vacancy_url not in urls:
                    urls.append(vacancy_url)
        except Exception as e:
            logger.error(f"Error parsing page {page}: {str(e)}")

    return urls

def collect_vacancy_data(urls: list) -> list:
    """Сбор данных по каждой вакансии"""
    data = []

    for url in urls:
        try:
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            title = soup.find('h1', {'data-qa': 'vacancy-title'})
            title = title.get_text(strip=True) if title else "Не указано"

            company = soup.find('a', {'data-qa': 'vacancy-company-name'})
            company = company.get_text(strip=True) if company else "Не указана"

            address = soup.find('p', {'data-qa': 'vacancy-view-location'})
            if not address:
                address = soup.find('span', {'data-qa': 'vacancy-view-raw-address'})
            address = address.get_text(strip=True) if address else "Не указан"

            salary = soup.find('span', {'data-qa': 'vacancy-salary-compensation'})
            salary = salary.get_text(strip=True) if salary else "Не указана"

            tax = "на руки" if "на руки" in salary.lower() else "до вычета налогов"

            data.append({
                "Название вакансии": title,
                "Компания": company,
                "Адрес": address,
                "Зарплата": salary,
                "Выдача": tax,
                "Ссылка": url
            })

        except Exception as e:
            logger.warning(f"Ошибка при обработке {url}: {str(e)}")

    return data

def save_data(data: list) -> tuple:
    """Сохранение данных в файлы"""
    df = pd.DataFrame(data)

    csv_path = "vacancies.csv"
    excel_path = "vacancies.xlsx"

    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    df.to_excel(excel_path, index=False)

    return csv_path, excel_path

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена операции"""
    await update.message.reply_text(
        "❌ Операция отменена. Чтобы начать заново, нажмите /start"
    )
    return ConversationHandler.END

def main() -> None:
    """Запуск бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            PAGES: [MessageHandler(filters.TEXT & ~filters.COMMAND, pages)],
            QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, query)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("cancel", cancel))

    logger.info("Бот запущен")
    application.run_polling()
    logger.info("Бот остановлен")

if __name__ == '__main__':
    main()
