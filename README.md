# hh-vacancy-bot 🤖

[![Python](https://img.shields.io/badge/Python-3.7%2B-blue?logo=python)](https://python.org)
[![PTB](https://img.shields.io/badge/PTB-20.0%2B-green?logo=telegram)](https://python-telegram-bot.org)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Telegram-бот для поиска вакансий на [HH.ru](https://hh.ru) с автоматическим экспортом результатов в **Excel (.xlsx)** и **CSV**. Простой диалоговый интерфейс — достаточно ввести запрос, и бот соберёт актуальные вакансии за минуту.

> 🔍 Работает с последней версией `python-telegram-bot` (v20.0+)

![Demo](docs/screenshots/demo.gif)

---

## 🚀 Возможности

- ✅ Пошаговый диалог: количество страниц → поисковый запрос
- ✅ Парсинг вакансий с HH.ru (название, компания, зарплата, адрес)
- ✅ Поддержка регионов (Сургут, Москва и др.)
- ✅ Экспорт данных в **CSV** и **Excel**
- ✅ Обработка ошибок и валидация ввода
- ✅ Совместимость с Python 3.7+

---

## 📦 Установка и запуск

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/ваш-ник/hh-vacancy-bot.git
cd hh-vacancy-bot
pip install -r requirements.txt
