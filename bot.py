import asyncio
import logging
import random
import os
import threading
from datetime import datetime, timedelta
from typing import Dict

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.utils import executor
from flask import Flask

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

BOT_TOKEN = "8675008414:AAGHkl8Udcz9F4AhZfZCDV-idIS3I1lbcmI"
ADMIN_ID = 7753887058
CRYPTO_WALLET = "UQDRRRGutl_ccP25XcwbOK-RN2UXuvE1_GFoerlaIDvmwO7I"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# FLASK ВЕБ-СЕРВЕР (ДЛЯ RENDER)
# ============================================

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Бот работает!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    app.run(host='0.0.0.0', port=10000)

# Запускаем Flask в отдельном потоке
thread = threading.Thread(target=run_flask, daemon=True)
thread.start()
logger.info("🌐 Веб-сервер запущен на порту 10000")

# ============================================
# БОТ
# ============================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

class PurchaseStates(StatesGroup):
    selecting_category = State()

PRODUCTS = {
    "меф": {"name": "Меф", "price": 15, "category": "соль", "emoji": "💎"},
    "a-pvp": {"name": "a-PvP", "price": 9, "category": "соль", "emoji": "⚗️"},
    "мдвп": {"name": "МДВП", "price": 13, "category": "соль", "emoji": "🧪"},
    "гашиш": {"name": "ГашNш", "price": 12, "category": "каннибиноиды", "emoji": "🌿"},
    "марихуанна": {"name": "Марихуанна", "price": 8, "category": "каннибиноиды", "emoji": "🍃"},
}

user_data: Dict[int, Dict] = {}
active_tickets: Dict[int, Dict] = {}
admin_tickets: Dict[int, int] = {}

# ============================================
# КЛАВИАТУРЫ
# ============================================

def get_main_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton(text="💠 Купить нарк0тy 💠", callback_data="buy"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
    )
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

# ============================================
# ОБРАБОТЧИКИ
# ============================================

@dp.message_handler(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {
            "purchases_today": 0,
            "cooldown_until": None,
            "balance": 0.0,
            "total_purchases": 0,
            "ticket": None,
            "in_chat": False
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
        f"🆔 ID: {user_id}\n"
        f"━━━━━━━━━━━━━━━━"
    )
    
    await callback.message.edit_text(profile_text, reply_markup=get_main_keyboard())
    await callback.answer()

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
    """При выборе товара сразу создается тикет"""
    user_id = callback.from_user.id
    product_key = callback.data.split("_")[1]
    product = PRODUCTS.get(product_key)
    
    if not product:
        await callback.answer("Товар не найден!", show_alert=True)
        return
    
    if not check_purchase_limit(user_id):
        await callback.answer("❌ Достигнут лимит покупок на сегодня!", show_alert=True)
        return
    
    # Создаем тикет
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
    admin_tickets[user_id] = ticket_number
    
    await state.finish()
    
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
# ОБРАБОТКА ТИКЕТОВ
# ============================================

@dp.callback_query_handler(lambda c: c.data.startswith("accept_ticket_"))
async def handle_accept_ticket(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    ticket_number = int(callback.data.split("_")[2])
    
    if ticket_number not in active_tickets:
        await callback.answer("❌ Тикет не найден!", show_alert=True)
        return
    
    ticket = active_tickets[ticket_number]
    user_id = ticket["user_id"]
    
    if user_id in user_data:
        user_data[user_id]["in_chat"] = True
    
    await callback.message.edit_text(
        f"✅ Тикет #{ticket_number} ПРИНЯТ!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👤 Пользователь: {user_id}\n"
        f"📦 Товар: {ticket['product']}\n"
        f"💰 Сумма: {ticket['price']} GRAM\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💬 Теперь вы можете общаться с клиентом.\n"
        f"Отправляйте текст, фото или геолокацию.",
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
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    ticket_number = int(callback.data.split("_")[2])
    
    if ticket_number not in active_tickets:
        await callback.answer("❌ Тикет не найден!", show_alert=True)
        return
    
    ticket = active_tickets[ticket_number]
    user_id = ticket["user_id"]
    
    if user_id in user_data:
        user_data[user_id]["in_chat"] = False
        user_data[user_id]["ticket"] = None
        user_data[user_id]["total_purchases"] += 1
    
    del active_tickets[ticket_number]
    if user_id in admin_tickets:
        del admin_tickets[user_id]
    
    try:
        await bot.send_message(
            user_id,
            f"❌ Тикет #{ticket_number} закрыт продавцом.\n"
            f"Спасибо за покупку! 🌟"
        )
    except:
        pass
    
    await callback.message.edit_text(
        f"❌ Тикет #{ticket_number} ЗАКРЫТ!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Покупка завершена."
    )
    
    await callback.answer("✅ Тикет закрыт!")

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
    
    await callback.message.edit_text(
        "🔚 Чат закрыт.\n"
        "Для новых покупок используйте главное меню.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

# ============================================
# СООБЩЕНИЯ В ЧАТЕ
# ============================================

@dp.message_handler(content_types=['text', 'photo', 'location'])
async def handle_chat_messages(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if user_id == ADMIN_ID:
        target_user = None
        target_ticket = None
        
        for ticket_num, ticket in active_tickets.items():
            if ticket["user_id"] == ADMIN_ID:
                continue
            if ticket["user_id"] in admin_tickets and admin_tickets[ticket["user_id"]] == ticket_num:
                target_user = ticket["user_id"]
                target_ticket = ticket_num
                break
        
        if not target_user:
            await message.answer("❌ Нет активного чата с пользователем.")
            return
        
        try:
            if message.text:
                await bot.send_message(target_user, f"🛒 Продавец: {message.text}")
            elif message.photo:
                await bot.send_photo(target_user, message.photo[-1].file_id, caption=f"🛒 Продавец: {message.caption or ''}")
            elif message.location:
                await bot.send_location(target_user, message.location.latitude, message.location.longitude)
                await bot.send_message(target_user, "📍 Продавец отправил геолокацию")
            
            await message.answer("✅ Сообщение отправлено пользователю.")
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await message.answer("❌ Ошибка отправки")
    
    else:
        if user_id not in user_data or not user_data[user_id].get("in_chat", False):
            await message.answer("❌ У вас нет активного чата.")
            return
        
        ticket_number = user_data[user_id].get("ticket")
        if not ticket_number or ticket_number not in active_tickets:
            await message.answer("❌ Тикет не найден.")
            return
        
        try:
            if message.text:
                await bot.send_message(ADMIN_ID, f"💬 От #{ticket_number}:\n{message.text}")
            elif message.photo:
                await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"💬 От #{ticket_number}:\n{message.caption or ''}")
            elif message.location:
                await bot.send_location(ADMIN_ID, message.location.latitude, message.location.longitude)
                await bot.send_message(ADMIN_ID, f"📍 Геолокация от #{ticket_number}")
            
            await message.answer("✅ Сообщение отправлено продавцу.")
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await message.answer("❌ Ошибка отправки")

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
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
    logger.info("🚀 Бот запускается...")
    logger.info("✅ Бот готов!")

if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
