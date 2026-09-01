import asyncio
import logging
import random
import os
import threading
import hashlib
import json
import sys
from datetime import datetime, timedelta
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.utils import executor
from flask import Flask

# ============================================
# КОНФИГУРАЦИЯ (ОСНОВНОЙ БОТ)
# ============================================

BOT_TOKEN = "8841797835:AAGD67q-kLD8DCV6GfedylCWwAofQJRiK-A"  # ТОКЕН ОСНОВНОГО БОТА
ADMIN_ID = 7753887058
CRYPTO_WALLET = "UQDRRRGutl_ccP25XcwbOK-RN2UXuvE1_GFoerlaIDvmwO7I"
BOT_USERNAME = "asoqwdjk_bot"

# ============================================
# РАСПОЗНАВАНИЕ РЕЖИМА
# ============================================

IS_MIRROR = False

# Если передан аргумент --mirror, то бот работает как зеркало
if len(sys.argv) > 1 and sys.argv[1] == "--mirror":
    IS_MIRROR = True
    # Загружаем конфиг зеркала (токен и данные основного бота)
    try:
        with open("mirror_config.json", "r") as f:
            config = json.load(f)
            MIRROR_TOKEN = config["token"]  # Токен зеркального бота
            MAIN_BOT_ID = config["main_bot_id"]  # ID основного бота
    except:
        print("❌ Ошибка загрузки конфигурации зеркала!")
        sys.exit(1)

# ============================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# ЗАПУСК FLASK (ТОЛЬКО ДЛЯ ОСНОВНОГО БОТА)
# ============================================

if not IS_MIRROR:
    app = Flask(__name__)

    @app.route('/')
    def health_check():
        return "Бот работает!", 200

    @app.route('/health')
    def health():
        return "OK", 200

    def run_flask():
        app.run(host='0.0.0.0', port=10000)

    thread = threading.Thread(target=run_flask, daemon=True)
    thread.start()
    logger.info("🌐 Веб-сервер запущен на порту 10000")

# ============================================
# СОЗДАНИЕ БОТА
# ============================================

if IS_MIRROR:
    bot = Bot(token=MIRROR_TOKEN)
    MAIN_BOT = Bot(token=BOT_TOKEN)  # Бот для отправки сообщений основному админу
else:
    bot = Bot(token=BOT_TOKEN)

dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# ============================================
# ДАННЫЕ
# ============================================

class PurchaseStates(StatesGroup):
    selecting_category = State()
    waiting_for_mirror_token = State()

PRODUCTS = {
    "меф": {"name": "Меф", "price": 15, "category": "соль", "emoji": "💎"},
    "a-pvp": {"name": "a-PvP", "price": 9, "category": "соль", "emoji": "⚗️"},
    "мдвп": {"name": "МДВП", "price": 13, "category": "соль", "emoji": "🧪"},
    "гашиш": {"name": "ГашNш", "price": 12, "category": "каннибиноиды", "emoji": "🌿"},
    "марихуанна": {"name": "Марихуанна", "price": 8, "category": "каннибиноиды", "emoji": "🍃"},
}

# Хранилище данных
user_data: Dict[int, Dict] = {}
active_tickets: Dict[int, Dict] = {}
referral_data: Dict[int, Dict] = {}
mirrors: Dict[int, Dict] = {}  # Только для основного бота

# Активный чат админа (только для основного бота)
current_admin_chat: Optional[int] = None
current_admin_user: Optional[int] = None

# ============================================
# РЕФЕРАЛЬНАЯ СИСТЕМА (ТОЛЬКО ДЛЯ ОСНОВНОГО БОТА)
# ============================================

def generate_referral_link(user_id: int) -> str:
    ref_code = hashlib.md5(str(user_id).encode()).hexdigest()[:8]
    return f"https://t.me/{BOT_USERNAME}?start=ref_{ref_code}"

def get_user_id_from_ref_code(ref_code: str) -> Optional[int]:
    for uid, data in referral_data.items():
        if data.get("ref_code") == ref_code:
            return uid
    return None

# ============================================
# ФУНКЦИЯ ПРОВЕРКИ ТОКЕНА
# ============================================

async def check_token_valid(token: str) -> tuple:
    try:
        test_bot = Bot(token=token)
        me = await test_bot.get_me()
        return True, me.username
    except:
        return False, None

# ============================================
# ФУНКЦИЯ ЗАПУСКА ЗЕРКАЛА
# ============================================

def start_mirror_bot(token: str, username: str, main_bot_id: int):
    """Запускает зеркальный бот в отдельном процессе"""
    try:
        # Создаем конфиг для зеркала
        config = {
            "token": token,
            "main_bot_id": main_bot_id
        }
        
        with open("mirror_config.json", "w") as f:
            json.dump(config, f)
        
        # Запускаем зеркало
        import subprocess
        process = subprocess.Popen(
            [sys.executable, "bot.py", "--mirror"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        logger.info(f"🪞 Зеркало @{username} запущено (PID: {process.pid})")
        return process
    except Exception as e:
        logger.error(f"Ошибка запуска зеркала: {e}")
        return None

# ============================================
# КЛАВИАТУРЫ
# ============================================

def get_main_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton(text="💠 Купить нарк0тy 💠", callback_data="buy"))
    keyboard.add(InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    
    # Дополнительные кнопки только для основного бота
    if not IS_MIRROR:
        keyboard.add(InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="referral"))
        keyboard.add(InlineKeyboardButton(text="🪞 Создать зеркало", callback_data="mirror"))
    
    return keyboard

def get_categories_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton(text="🧂 Соль", callback_data="category_salt"),
        InlineKeyboardButton(text="🌿 Каннибиноиды", callback_data="category_cannabis"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
    )
    return keyboard

def get_products_keyboard(category: str):
    keyboard = InlineKeyboardMarkup(row_width=1)
    for key, product in PRODUCTS.items():
        if product["category"] == category:
            keyboard.add(InlineKeyboardButton(
                text=f"{product['emoji']} {product['name']} - {product['price']} GRAM",
                callback_data=f"product_{key}"
            ))
    keyboard.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_categories"))
    return keyboard

def get_admin_ticket_keyboard(ticket_number: int):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton(
        text=f"✅ Принять тикет #{ticket_number}",
        callback_data=f"accept_ticket_{ticket_number}"
    ))
    return keyboard

def get_admin_chat_keyboard(ticket_number: int):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton(
        text=f"❌ Закрыть Тикет #{ticket_number}",
        callback_data=f"close_ticket_{ticket_number}"
    ))
    return keyboard

def get_user_chat_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton(text="❌ Закрыть чат", callback_data="close_user_chat"))
    return keyboard

def get_back_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return keyboard

# ============================================
# ФУНКЦИЯ УДАЛЕНИЯ ЧАТА
# ============================================

async def delete_chat_messages(user_id: int):
    try:
        for i in range(10):
            try:
                messages = await bot.get_chat_history(chat_id=user_id, limit=10)
                if not messages:
                    break
                for msg in messages:
                    try:
                        await bot.delete_message(chat_id=user_id, message_id=msg.message_id)
                    except:
                        pass
                await asyncio.sleep(0.5)
            except:
                break
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщений: {e}")

# ============================================
# ОБРАБОТЧИКИ ДЛЯ ВСЕХ (ОСНОВНОЙ + ЗЕРКАЛО)
# ============================================

@dp.message_handler(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    args = message.get_args()
    
    if user_id not in user_data:
        user_data[user_id] = {
            "purchases_today": 0,
            "cooldown_until": None,
            "balance": 0.0,
            "total_purchases": 0,
            "ticket": None,
            "in_chat": False
        }
        
        # Реферальная система только для основного бота
        if not IS_MIRROR:
            user_data[user_id]["ref_code"] = hashlib.md5(str(user_id).encode()).hexdigest()[:8]
            user_data[user_id]["invited_users"] = 0
            referral_data[user_id] = {
                "ref_code": user_data[user_id]["ref_code"],
                "ref_link": generate_referral_link(user_id),
                "invited_users": 0
            }
    
    if user_data[user_id].get("in_chat", False):
        await message.answer("Вы находитесь в активном чате с продавцом.")
        return
    
    welcome_text = (
        "Привет, это бот для покупки наркотиков!\n"
        "Здесь есть ассортимент наркотиков по типу солей, каннибиноиды.\n"
        "После выбора товара создается тикет, и вы общаетесь с продавцом напрямую.\n"
        "Оплата производится в криптовалюте GRAM.\n"
        "Всех благ и хороших покупок."
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "buy")
async def handle_buy(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if not check_cooldown(user_id):
        await callback.answer("⚠️ У вас активен кулдаун!", show_alert=True)
        return
    
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_categories_keyboard())
    await callback.answer()
    await state.set_state(PurchaseStates.selecting_category)

@dp.callback_query_handler(lambda c: c.data == "profile")
async def handle_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    data = user_data.get(user_id, {"purchases_today": 0, "total_purchases": 0, "balance": 0})
    
    profile_text = (
        f"👤 Ваш профиль:\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📦 Покупки сегодня: {data.get('purchases_today', 0)}/2\n"
        f"🔄 Всего покупок: {data.get('total_purchases', 0)}\n"
        f"💰 Баланс: {data.get('balance', 0):.2f} GRAM\n"
    )
    
    # Дополнительная информация для основного бота
    if not IS_MIRROR:
        user_mirrors = mirrors.get(user_id, {})
        profile_text += f"👥 Приглашено: {data.get('invited_users', 0)}\n"
        profile_text += f"🪞 Зеркал создано: {len(user_mirrors)}\n"
    
    profile_text += f"🆔 ID: {user_id}\n"
    profile_text += f"━━━━━━━━━━━━━━━━"
    
    await callback.message.edit_text(profile_text, reply_markup=get_back_keyboard())
    await callback.answer()

# ============================================
# ОБРАБОТЧИКИ ТОЛЬКО ДЛЯ ОСНОВНОГО БОТА
# ============================================

if not IS_MIRROR:
    
    @dp.callback_query_handler(lambda c: c.data == "referral")
    async def handle_referral(callback: CallbackQuery):
        user_id = callback.from_user.id
        
        if user_id not in user_data:
            await callback.answer("❌ Ошибка! Напишите /start", show_alert=True)
            return
        
        ref_link = generate_referral_link(user_id)
        invited = user_data[user_id].get("invited_users", 0)
        
        text = (
            f"🔗 Ваша реферальная ссылка:\n"
            f"`{ref_link}`\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 Приглашено: {invited} человек\n"
            f"💰 Бонус: 2 GRAM за каждого приглашенного\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📤 Отправьте эту ссылку друзьям!"
        )
        
        await callback.message.edit_text(text, reply_markup=get_back_keyboard(), parse_mode="Markdown")
        await callback.answer()
    
    @dp.callback_query_handler(lambda c: c.data == "mirror")
    async def handle_mirror(callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        
        # Проверяем лимит зеркал (максимум 10)
        user_mirrors = mirrors.get(user_id, {})
        if len(user_mirrors) >= 10:
            await callback.answer("❌ Максимум 10 зеркал на пользователя!", show_alert=True)
            return
        
        text = (
            "🪞 СОЗДАНИЕ ЗЕРКАЛА\n"
            "━━━━━━━━━━━━━━━━\n"
            "1️⃣ Создайте нового бота в @BotFather\n"
            "2️⃣ Скопируйте его токен\n"
            "3️⃣ Вставьте токен сюда\n"
            "━━━━━━━━━━━━━━━━\n"
            "❗ Все тикеты будут приходить основному админу.\n"
            "❌ Напишите /cancel для отмены."
        )
        
        await callback.message.edit_text(text, reply_markup=get_back_keyboard())
        await state.set_state(PurchaseStates.waiting_for_mirror_token)
        await callback.answer()
    
    @dp.message_handler(state=PurchaseStates.waiting_for_mirror_token)
    async def process_mirror_token(message: Message, state: FSMContext):
        user_id = message.from_user.id
        token = message.text.strip()
        
        # Проверяем токен
        is_valid, username = await check_token_valid(token)
        
        if not is_valid:
            await message.answer(
                "❌ НЕДЕЙСТВИТЕЛЬНЫЙ ТОКЕН!\n"
                "Убедитесь, что вы правильно скопировали токен из @BotFather.\n"
                "Попробуйте снова или напишите /cancel",
                reply_markup=get_back_keyboard()
            )
            return
        
        # Запускаем зеркало
        process = start_mirror_bot(token, username, ADMIN_ID)
        
        if process is None:
            await message.answer(
                "❌ Ошибка при создании зеркала!\n"
                "Попробуйте позже.",
                reply_markup=get_main_keyboard()
            )
            await state.finish()
            return
        
        # Сохраняем зеркало
        if user_id not in mirrors:
            mirrors[user_id] = {}
        
        mirrors[user_id][username] = {
            "token": token,
            "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "active": True,
            "process": process
        }
        
        await message.answer(
            f"✅ ЗЕРКАЛО СОЗДАНО УСПЕШНО!\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🤖 Бот: @{username}\n"
            f"📅 Создан: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
            f"🪞 Всего зеркал: {len(mirrors[user_id])}/10\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🔗 Ссылка: https://t.me/{username}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"✅ Все тикеты будут приходить основному админу @{BOT_USERNAME}.",
            reply_markup=get_main_keyboard()
        )
        
        await state.finish()

# ============================================
# ОБРАБОТЧИКИ ПОКУПОК (ДЛЯ ВСЕХ)
# ============================================

@dp.callback_query_handler(lambda c: c.data == "back_to_main")
async def handle_back_to_main(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_data[user_id].get("in_chat", False):
        await callback.answer("⚠️ Вы не можете выйти из чата!", show_alert=True)
        return
    
    welcome_text = (
        "Привет, это бот для покупки наркотиков!\n"
        "Здесь есть ассортимент наркотиков по типу солей, каннибиноиды.\n"
        "После выбора товара создается тикет, и вы общаетесь с продавцом напрямую.\n"
        "Оплата производится в криптовалюте GRAM.\n"
        "Всех благ и хороших покупок."
    )
    await callback.message.edit_text(welcome_text, reply_markup=get_main_keyboard())
    await state.finish()
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "back_to_categories")
async def handle_back_to_categories(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_categories_keyboard())
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("category_"))
async def handle_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[1]
    category_map = {"salt": "соль", "cannabis": "каннибиноиды"}
    category_name = category_map.get(category, "")
    
    await callback.message.edit_text(
        f"Выберите продукт из категории '{category_name}':",
        reply_markup=get_products_keyboard(category_name)
    )
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("product_"))
async def handle_product(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    product_key = callback.data.split("_")[1]
    product = PRODUCTS.get(product_key)
    
    if not product:
        await callback.answer("Товар не найден!", show_alert=True)
        return
    
    if not check_purchase_limit(user_id):
        await callback.answer("❌ Достигнут лимит покупок на сегодня!", show_alert=True)
        return
    
    ticket_number = random.randint(1, 150000)
    
    if user_id not in user_data:
        user_data[user_id] = {"purchases_today": 0, "total_purchases": 0, "balance": 0}
    
    user_data[user_id]["purchases_today"] += 1
    user_data[user_id]["total_purchases"] += 1
    user_data[user_id]["ticket"] = ticket_number
    
    if user_data[user_id]["purchases_today"] >= 2:
        user_data[user_id]["cooldown_until"] = datetime.now() + timedelta(hours=24)
    else:
        user_data[user_id]["cooldown_until"] = datetime.now() + timedelta(hours=5)
    
    active_tickets[ticket_number] = {
        "user_id": user_id,
        "product": product["name"],
        "price": product["price"],
        "created_at": datetime.now()
    }
    
    await state.finish()
    
    # Сообщение пользователю
    await callback.message.edit_text(
        f"✅ Вы выбрали {product['emoji']} {product['name']}!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🎫 Ваш тикет создан! #{ticket_number}\n"
        f"💰 Стоимость: {product['price']} GRAM\n"
        f"📤 Оплата на кошелек: `{CRYPTO_WALLET}`\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"⏳ Ожидайте, продавец свяжется с вами в этом чате!",
        parse_mode="Markdown"
    )
    
    # ✅ ЕСЛИ ЭТО ЗЕРКАЛО — ОТПРАВЛЯЕМ УВЕДОМЛЕНИЕ ОСНОВНОМУ АДМИНУ
    if IS_MIRROR:
        # Отправляем уведомление основному админу (через основного бота)
        admin_message = (
            f"🔔 НОВАЯ ПОКУПКА В ЗЕРКАЛЕ!\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🎫 Тикет: #{ticket_number}\n"
            f"👤 Пользователь: {user_id}\n"
            f"📦 Товар: {product['name']}\n"
            f"💰 Сумма: {product['price']} GRAM\n"
            f"🤖 Бот: @{BOT_USERNAME}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Ожидает принятия!"
        )
        
        await MAIN_BOT.send_message(
            ADMIN_ID,
            admin_message,
            reply_markup=get_admin_ticket_keyboard(ticket_number)
        )
    else:
        # Основной бот — отправляем уведомление админу напрямую
        admin_message = (
            f"🔔 НОВАЯ ПОКУПКА!\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🎫 Тикет: #{ticket_number}\n"
            f"👤 Пользователь: {user_id}\n"
            f"📦 Товар: {product['name']}\n"
            f"💰 Сумма: {product['price']} GRAM\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Ожидает принятия!"
        )
        
        await bot.send_message(
            ADMIN_ID,
            admin_message,
            reply_markup=get_admin_ticket_keyboard(ticket_number)
        )
    
    await callback.answer("✅ Тикет создан!")

# ============================================
# ОБРАБОТЧИКИ АДМИНА (ТОЛЬКО ДЛЯ ОСНОВНОГО БОТА)
# ============================================

if not IS_MIRROR:
    
    @dp.callback_query_handler(lambda c: c.data.startswith("accept_ticket_"))
    async def handle_accept_ticket(callback: CallbackQuery):
        global current_admin_chat, current_admin_user
        
        if callback.from_user.id != ADMIN_ID:
            await callback.answer("❌ У вас нет доступа!", show_alert=True)
            return
        
        ticket_number = int(callback.data.split("_")[2])
        
        if ticket_number not in active_tickets:
            await callback.answer("❌ Тикет не найден!", show_alert=True)
            return
        
        if current_admin_chat is not None:
            await callback.answer(
                f"❌ У вас уже активен чат с тикетом #{current_admin_chat}!",
                show_alert=True
            )
            return
        
        ticket = active_tickets[ticket_number]
        user_id = ticket["user_id"]
        
        current_admin_chat = ticket_number
        current_admin_user = user_id
        
        if user_id in user_data:
            user_data[user_id]["in_chat"] = True
        
        await callback.message.edit_text(
            f"✅ Тикет #{ticket_number} ПРИНЯТ!\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 Пользователь: {user_id}\n"
            f"📦 Товар: {ticket['product']}\n"
            f"💰 Сумма: {ticket['price']} GRAM\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💬 Теперь вы общаетесь с этим клиентом.",
            reply_markup=get_admin_chat_keyboard(ticket_number)
        )
        
        await bot.send_message(
            user_id,
            f"✅ Продавец принял ваш тикет #{ticket_number}!\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💬 Теперь вы можете общаться с продавцом.",
            reply_markup=get_user_chat_keyboard()
        )
        
        await callback.answer("✅ Тикет принят!")
    
    @dp.callback_query_handler(lambda c: c.data.startswith("close_ticket_"))
    async def handle_close_ticket(callback: CallbackQuery):
        global current_admin_chat, current_admin_user
        
        if callback.from_user.id != ADMIN_ID:
            await callback.answer("❌ У вас нет доступа!", show_alert=True)
            return
        
        ticket_number = int(callback.data.split("_")[2])
        
        if current_admin_chat != ticket_number:
            await callback.answer("❌ Этот тикет не активен!", show_alert=True)
            return
        
        if ticket_number not in active_tickets:
            await callback.answer("❌ Тикет не найден!", show_alert=True)
            return
        
        ticket = active_tickets[ticket_number]
        user_id = ticket["user_id"]
        
        try:
            await delete_chat_messages(user_id)
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
        
        if user_id in user_data:
            user_data[user_id]["in_chat"] = False
            user_data[user_id]["ticket"] = None
            user_data[user_id]["total_purchases"] += 1
        
        del active_tickets[ticket_number]
        
        current_admin_chat = None
        current_admin_user = None
        
        try:
            await bot.delete_message(chat_id=ADMIN_ID, message_id=callback.message.message_id)
        except:
            pass
        
        await bot.send_message(
            ADMIN_ID,
            f"❌ Тикет #{ticket_number} ЗАКРЫТ!\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Покупка завершена.\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"✅ Можно принять новый тикет."
        )
        
        if active_tickets:
            waiting_list = "\n".join([f"#{t}" for t in active_tickets.keys()])
            await bot.send_message(ADMIN_ID, f"📋 Ожидают принятия:\n{waiting_list}")
        
        await callback.answer("✅ Тикет закрыт!")

# ============================================
# ЗАКРЫТИЕ ЧАТА ПОЛЬЗОВАТЕЛЕМ (ДЛЯ ВСЕХ)
# ============================================

@dp.callback_query_handler(lambda c: c.data == "close_user_chat")
async def handle_close_user_chat(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in user_data or not user_data[user_id].get("in_chat", False):
        await callback.answer("❌ У вас нет активного чата!", show_alert=True)
        return
    
    ticket_number = user_data[user_id].get("ticket")
    if ticket_number and ticket_number in active_tickets:
        await callback.answer("❌ Вы не можете закрыть чат, пока тикет активен!", show_alert=True)
        return
    
    user_data[user_id]["in_chat"] = False
    
    try:
        await bot.delete_message(chat_id=user_id, message_id=callback.message.message_id)
    except:
        pass
    
    await bot.send_message(
        user_id,
        "🔚 Чат закрыт.\n"
        "Для новых покупок используйте главное меню.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

# ============================================
# СООБЩЕНИЯ В ЧАТЕ (ТОЛЬКО ДЛЯ ОСНОВНОГО БОТА)
# ============================================

if not IS_MIRROR:
    
    @dp.message_handler(content_types=['text', 'photo', 'location'])
    async def handle_chat_messages(message: Message, state: FSMContext):
        global current_admin_chat, current_admin_user
        
        user_id = message.from_user.id
        
        if user_id == ADMIN_ID:
            if current_admin_chat is None:
                await message.answer("❌ Нет активного чата.")
                return
            
            try:
                if message.text:
                    await bot.send_message(current_admin_user, f"🛒 Продавец: {message.text}")
                elif message.photo:
                    await bot.send_photo(current_admin_user, message.photo[-1].file_id, caption=f"🛒 Продавец: {message.caption or ''}")
                elif message.location:
                    await bot.send_location(current_admin_user, message.location.latitude, message.location.longitude)
                    await bot.send_message(current_admin_user, "📍 Продавец отправил геолокацию")
                
                await message.answer(f"✅ Сообщение отправлено (тикет #{current_admin_chat}).")
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                await message.answer("❌ Ошибка отправки")
        
        else:
            if current_admin_chat is None:
                await message.answer("❌ Продавец еще не принял ваш тикет.")
                return
            
            ticket = active_tickets.get(current_admin_chat)
            if not ticket or ticket["user_id"] != user_id:
                await message.answer("❌ Вы не в активном чате.")
                return
            
            if not user_data[user_id].get("in_chat", False):
                await message.answer("❌ У вас нет активного чата.")
                return
            
            try:
                if message.text:
                    await bot.send_message(ADMIN_ID, f"💬 От #{current_admin_chat}:\n{message.text}")
                elif message.photo:
                    await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"💬 От #{current_admin_chat}:\n{message.caption or ''}")
                elif message.location:
                    await bot.send_location(ADMIN_ID, message.location.latitude, message.location.longitude)
                    await bot.send_message(ADMIN_ID, f"📍 Геолокация от #{current_admin_chat}")
                
                await message.answer("✅ Сообщение отправлено продавцу.")
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                await message.answer("❌ Ошибка отправки")

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (ДЛЯ ВСЕХ)
# ============================================

def check_cooldown(user_id: int) -> bool:
    if user_id not in user_data:
        return True
    
    cooldown_until = user_data[user_id].get("cooldown_until")
    if not cooldown_until:
        return True
    
    if datetime.now() >= cooldown_until:
        user_data[user_id]["purchases_today"] = 0
        user_data[user_id]["cooldown_until"] = None
        return True
    
    return False

def check_purchase_limit(user_id: int) -> bool:
    if user_id not in user_data:
        return True
    
    purchases_today = user_data[user_id].get("purchases_today", 0)
    return purchases_today < 2

# ============================================
# ЗАПУСК
# ============================================

async def on_startup(dp):
    if IS_MIRROR:
        logger.info("🪞 Зеркальный бот запущен! Все тикеты идут основному админу.")
    else:
        logger.info("🚀 Основной бот запущен!")
        logger.info(f"👤 Админ: {ADMIN_ID}")
    
    logger.info("✅ Бот готов!")

if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
