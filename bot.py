import asyncio
import logging
import random
import os
from datetime import datetime, timedelta
from typing import Dict, Tuple
import aiohttp

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.utils import executor
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

BOT_TOKEN = os.getenv("8675008414:AAGHkl8Udcz9F4AhZfZCDV-idIS3I1lbcmI")
ADMIN_ID = int(os.getenv("ADMIN_ID", 7753887058))
CRYPTO_WALLET = os.getenv("CRYPTO_WALLET", "UQDRRRGutl_ccP25XcwbOK-RN2UXuvE1_GFoerlaIDvmwO7I")
TON_API_KEY = os.getenv("4077e5a978e350fcc0faad1d128a41a1a15c64ededc541e3681d28332ac0507f")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле!")
if not TON_API_KEY:
    raise ValueError("TON_API_KEY не найден в .env файле!")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# ============================================
# ДАННЫЕ
# ============================================

class PurchaseStates(StatesGroup):
    selecting_product = State()
    selecting_dosage = State()
    waiting_for_payment = State()

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
pending_payments: Dict[int, Dict] = {}
used_transactions = set()

# ============================================
# TON HANDLER
# ============================================

class TonHandler:
    def __init__(self, wallet_address: str, api_key: str):
        self.wallet_address = wallet_address
        self.api_key = api_key
        self.base_url = "https://toncenter.com/api/v2/"
    
    async def get_balance(self) -> float:
        try:
            url = f"{self.base_url}getAddressInformation"
            params = {"address": self.wallet_address}
            headers = {"X-API-Key": self.api_key}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        balance = int(data.get("result", {}).get("balance", 0)) / 1e9
                        logger.info(f"Баланс: {balance} TON")
                        return balance
                    return 0
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return 0
    
    async def check_payment(self, amount: float, user_id: int) -> Tuple[bool, str]:
        try:
            url = f"{self.base_url}getTransactions"
            params = {"address": self.wallet_address, "limit": 20, "archival": True}
            headers = {"X-API-Key": self.api_key}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status != 200:
                        return False, ""
                    
                    data = await response.json()
                    transactions = data.get("result", [])
                    
                    for tx in transactions:
                        if tx.get("out_msgs", []):
                            continue
                        
                        tx_amount = int(tx.get("value", 0)) / 1e9
                        tx_hash = tx.get("transaction_id", {}).get("hash", "")
                        
                        if abs(tx_amount - amount) <= amount * 0.05 and tx_hash not in used_transactions:
                            used_transactions.add(tx_hash)
                            logger.info(f"✅ Найдена транзакция: {tx_hash}")
                            return True, tx_hash
                    
                    return False, ""
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            return False, ""

ton_handler = TonHandler(CRYPTO_WALLET, TON_API_KEY)

# ============================================
# КЛАВИАТУРЫ
# ============================================

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💠 Купить нарк0тy 💠", callback_data="buy"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
    )
    return builder.as_markup()

def get_categories_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🧂 Соль", callback_data="category_salt"))
    builder.row(InlineKeyboardButton(text="🌿 Каннибиноиды", callback_data="category_cannabis"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_products_keyboard(category: str):
    builder = InlineKeyboardBuilder()
    for key, product in PRODUCTS.items():
        if product["category"] == category:
            builder.row(InlineKeyboardButton(
                text=f"{product['emoji']} {product['name']} - {product['price']} GRAM",
                callback_data=f"product_{key}"
            ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_categories"))
    return builder.as_markup()

def get_dosage_keyboard(product_key: str, dosage: int, price: float):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➖", callback_data=f"dosage_down_{product_key}"),
        InlineKeyboardButton(text=f"{dosage}г", callback_data="ignore"),
        InlineKeyboardButton(text="➕", callback_data=f"dosage_up_{product_key}")
    )
    builder.row(InlineKeyboardButton(
        text=f"💰 Купить за {price:.2f} GRAM",
        callback_data=f"confirm_purchase_{product_key}"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_products"))
    return builder.as_markup()

def get_admin_ticket_keyboard(ticket_number: int):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"✅ Принять тикет #{ticket_number}",
        callback_data=f"accept_ticket_{ticket_number}"
    ))
    return builder.as_markup()

def get_admin_chat_keyboard(ticket_number: int):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"❌ Закрыть Тикет #{ticket_number}",
        callback_data=f"close_ticket_{ticket_number}"
    ))
    return builder.as_markup()

def get_user_chat_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Закрыть чат", callback_data="close_user_chat"))
    return builder.as_markup()

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
        "Покупка производиться строго в криптовалюте GRAM по криптокошельку указанному в покупке!!\n"
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
    await state.set_state(PurchaseStates.selecting_product)

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
        "Покупка производиться строго в криптовалюте GRAM по криптокошельку указанному в покупке!!\n"
        "Всех благ и хороших покупок."
    )
    await callback.message.edit_text(welcome_text, reply_markup=get_main_keyboard())
    await state.finish()
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "back_to_categories")
async def handle_back_to_categories(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_categories_keyboard())
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "back_to_products")
async def handle_back_to_products(callback: CallbackQuery, state: FSMContext):
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
    product_key = callback.data.split("_")[1]
    product = PRODUCTS.get(product_key)
    
    if not product:
        await callback.answer("Товар не найден!", show_alert=True)
        return
    
    await state.update_data(product_key=product_key, dosage=1, price=product["price"])
    
    await callback.message.edit_text(
        f"{product['emoji']} Отлично! Вы покупаете {product['name']}!\n"
        f"Стоимость: {product['price']} GRAM за 1 грамм\n"
        f"Измените дозировку и нажмите 'Купить'",
        reply_markup=get_dosage_keyboard(product_key, 1, product['price'])
    )
    await state.set_state(PurchaseStates.selecting_dosage)
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("dosage_up_"))
async def handle_dosage_up(callback: CallbackQuery, state: FSMContext):
    product_key = callback.data.split("_")[2]
    await update_dosage(callback, state, product_key, 1)

@dp.callback_query_handler(lambda c: c.data.startswith("dosage_down_"))
async def handle_dosage_down(callback: CallbackQuery, state: FSMContext):
    product_key = callback.data.split("_")[2]
    await update_dosage(callback, state, product_key, -1)

async def update_dosage(callback: CallbackQuery, state: FSMContext, product_key: str, delta: int):
    data = await state.get_data()
    current_dosage = data.get("dosage", 1)
    base_price = PRODUCTS[product_key]["price"]
    
    new_dosage = max(1, current_dosage + delta)
    new_price = base_price * (1.25 ** (new_dosage - 1))
    
    await state.update_data(dosage=new_dosage, price=new_price)
    
    await callback.message.edit_reply_markup(
        reply_markup=get_dosage_keyboard(product_key, new_dosage, new_price)
    )
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("confirm_purchase_"))
async def handle_confirm_purchase(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    product_key = callback.data.split("_")[2]
    data = await state.get_data()
    
    product = PRODUCTS[product_key]
    dosage = data.get("dosage", 1)
    price = data.get("price", product["price"])
    
    if not check_purchase_limit(user_id):
        await callback.answer("❌ Достигнут лимит покупок на сегодня!", show_alert=True)
        return
    
    pending_payments[user_id] = {
        "user_id": user_id,
        "product_key": product_key,
        "product": product["name"],
        "dosage": dosage,
        "amount": price,
        "status": "pending"
    }
    
    payment_text = (
        f"💰 Оплата покупки\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Товар: {product['name']}\n"
        f"Дозировка: {dosage}г\n"
        f"Сумма: {price:.2f} GRAM\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📤 Отправьте ровно {price:.2f} GRAM на кошелек:\n"
        f"`{CRYPTO_WALLET}`\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"⏳ После отправки нажмите '✅ Проверить оплату'"
    )
    
    await callback.message.edit_text(
        payment_text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Проверить оплату", callback_data="check_payment")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_products")]
            ]
        ),
        parse_mode="Markdown"
    )
    await state.set_state(PurchaseStates.waiting_for_payment)
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "check_payment")
async def handle_check_payment(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if user_id not in pending_payments:
        await callback.answer("❌ Платеж не найден!", show_alert=True)
        return
    
    payment = pending_payments[user_id]
    product = PRODUCTS[payment["product_key"]]
    
    await callback.message.edit_text("⏳ Проверка оплаты...")
    
    success, tx_hash = await ton_handler.check_payment(payment["amount"], user_id)
    
    if success:
        await complete_purchase(callback, state, user_id, product, payment["dosage"], payment["amount"], tx_hash)
    else:
        await callback.message.edit_text(
            f"❌ Оплата не найдена.\n"
            f"Проверьте, что вы отправили ровно {payment['amount']:.2f} GRAM\n"
            f"на кошелек: `{CRYPTO_WALLET}`",
            parse_mode="Markdown"
        )
        if user_id in pending_payments:
            del pending_payments[user_id]

async def complete_purchase(callback: CallbackQuery, state: FSMContext, user_id: int,
                            product: Dict, dosage: int, amount: float, tx_hash: str = None):
    
    if user_id not in user_data:
        user_data[user_id] = {"purchases_today": 0, "total_purchases": 0, "balance": 0}
    
    user_data[user_id]["purchases_today"] += 1
    user_data[user_id]["total_purchases"] += 1
    user_data[user_id]["last_purchase_time"] = datetime.now()
    
    if user_data[user_id]["purchases_today"] >= 2:
        user_data[user_id]["cooldown_until"] = datetime.now() + timedelta(hours=24)
    else:
        user_data[user_id]["cooldown_until"] = datetime.now() + timedelta(hours=5)
    
    ticket_number = random.randint(1, 150000)
    user_data[user_id]["ticket"] = ticket_number
    
    active_tickets[ticket_number] = {
        "user_id": user_id,
        "product": product["name"],
        "dosage": dosage,
        "amount": amount,
        "tx_hash": tx_hash,
        "created_at": datetime.now()
    }
    admin_tickets[user_id] = ticket_number
    
    if user_id in pending_payments:
        del pending_payments[user_id]
    
    await state.finish()
    
    await callback.message.edit_text(
        f"✅ Спасибо за покупку!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔄 Создается тикет...\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🎫 Ваш тикет создан! #{ticket_number}\n"
        f"⏳ Ждите сообщение от продавца!\n"
        f"В течении 10 минут - 5 часов!\n"
        f"━━━━━━━━━━━━━━━━"
    )
    
    admin_message = (
        f"🔔 НОВАЯ ПОКУПКА!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🎫 Тикет: #{ticket_number}\n"
        f"👤 Пользователь: {user_id}\n"
        f"📦 Товар: {product['name']}\n"
        f"⚖️ Дозировка: {dosage}г\n"
        f"💰 Сумма: {amount:.2f} GRAM\n"
        f"🔗 Хеш: {tx_hash or 'Не указан'}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Ожидает принятия!"
    )
    
    await bot.send_message(
        ADMIN_ID,
        admin_message,
        reply_markup=get_admin_ticket_keyboard(ticket_number)
    )
    
    await callback.answer("✅ Покупка завершена успешно!")

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
        f"⚖️ Дозировка: {ticket['dosage']}г\n"
        f"💰 Сумма: {ticket['amount']:.2f} GRAM\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💬 Отправляйте текст, фото или геолокацию.\n"
        f"━━━━━━━━━━━━━━━━",
        reply_markup=get_admin_chat_keyboard(ticket_number)
    )
    
    await bot.send_message(
        user_id,
        f"✅ Продавец принял ваш тикет #{ticket_number}!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💬 Теперь вы можете общаться с продавцом.\n"
        f"━━━━━━━━━━━━━━━━",
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
            f"Спасибо за покупку! Возвращайтесь снова. 🌟"
        )
    except:
        pass
    
    await callback.message.edit_text(
        f"❌ Тикет #{ticket_number} ЗАКРЫТ!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Покупка завершена.\n"
        f"━━━━━━━━━━━━━━━━"
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
    
    try:
        balance = await ton_handler.get_balance()
        logger.info(f"💰 Баланс: {balance} TON")
    except Exception as e:
        logger.error(f"❌ Ошибка TON: {e}")
    
    logger.info("✅ Бот готов!")

if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
