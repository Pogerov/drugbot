# ============================================
# bot_full.py - Полный рабочий код бота
# ============================================

import asyncio
import logging
import random
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import hashlib
import aiohttp

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

BOT_TOKEN = "8675008414:AAGHkl8Udcz9F4AhZfZCDV-idIS3I1lbcmI"  # Замените на реальный токен от @BotFather
ADMIN_ID = 7753887058  # Ваш Telegram ID
CRYPTO_WALLET = "UQDRRRGutl_ccP25XcwbOK-RN2UXuvE1_GFoerlaIDvmwO7I"  # Ваш кошелек
TON_API_KEY = "4077e5a978e350fcc0faad1d128a41a1a15c64ededc541e3681d28332ac0507f"  # Ваш API ключ

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ============================================
# СОСТОЯНИЯ FSM
# ============================================

class PurchaseStates(StatesGroup):
    selecting_product = State()
    selecting_dosage = State()
    waiting_for_payment = State()

# ============================================
# ДАННЫЕ ПРОДУКТОВ
# ============================================

PRODUCTS = {
    "меф": {"name": "Меф", "price": 15, "category": "соль", "emoji": "💎"},
    "a-pvp": {"name": "a-PvP", "price": 9, "category": "соль", "emoji": "⚗️"},
    "мдвп": {"name": "МДВП", "price": 13, "category": "соль", "emoji": "🧪"},
    "гашиш": {"name": "ГашNш", "price": 12, "category": "каннибиноиды", "emoji": "🌿"},
    "марихуанна": {"name": "Марихуанна", "price": 8, "category": "каннибиноиды", "emoji": "🍃"},
}

# ============================================
# ХРАНИЛИЩЕ ДАННЫХ
# ============================================

user_data: Dict[int, Dict] = {}
active_tickets: Dict[int, Dict] = {}
admin_tickets: Dict[int, int] = {}
pending_payments: Dict[int, Dict] = {}
used_transactions: set = set()
payment_checks: Dict[int, Dict] = {}

# ============================================
# КЛАСС ДЛЯ РАБОТЫ С TON
# ============================================

class TonHandler:
    def __init__(self, wallet_address: str, api_key: str):
        self.wallet_address = wallet_address
        self.api_key = api_key
        self.base_url = "https://toncenter.com/api/v2/"
        self.last_checked_balance = 0
        self.last_check_time = None
        
    async def get_balance(self) -> float:
        """Получение баланса кошелька"""
        try:
            url = f"{self.base_url}getAddressInformation"
            params = {"address": self.wallet_address}
            headers = {"X-API-Key": self.api_key}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        balance = int(data.get("result", {}).get("balance", 0)) / 1e9
                        logger.info(f"Баланс кошелька: {balance} TON")
                        return balance
                    else:
                        logger.error(f"Ошибка получения баланса: {response.status}")
                        return 0
        except Exception as e:
            logger.error(f"Ошибка при получении баланса: {e}")
            return 0
    
    async def get_transactions(self, limit: int = 50) -> list:
        """Получение последних транзакций"""
        try:
            url = f"{self.base_url}getTransactions"
            params = {
                "address": self.wallet_address,
                "limit": limit,
                "archival": True
            }
            headers = {"X-API-Key": self.api_key}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        transactions = data.get("result", [])
                        logger.info(f"Получено {len(transactions)} транзакций")
                        return transactions
                    else:
                        logger.error(f"Ошибка получения транзакций: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Ошибка при получении транзакций: {e}")
            return []
    
    async def check_payment(self, amount: float, user_id: int) -> Tuple[bool, Optional[str]]:
        """
        Проверка поступления средств на кошелек.
        Возвращает: (успех, хеш_транзакции)
        """
        try:
            logger.info(f"Проверка оплаты {amount} GRAM для пользователя {user_id}")
            
            # Получаем последние транзакции
            transactions = await self.get_transactions(limit=20)
            
            if not transactions:
                logger.warning("Нет транзакций для проверки")
                return False, None
            
            # Проверяем каждую транзакцию
            for tx in transactions:
                # Проверяем, что это входящая транзакция
                if tx.get("out_msgs", []):
                    continue
                
                # Получаем сумму в TON
                tx_amount = int(tx.get("value", 0)) / 1e9
                tx_hash = tx.get("transaction_id", {}).get("hash", "")
                tx_time = tx.get("utime", 0)
                
                # Проверяем сумму (с погрешностью 5%)
                if abs(tx_amount - amount) <= amount * 0.05:
                    # Проверяем, не была ли транзакция уже использована
                    if tx_hash not in used_transactions:
                        # Проверяем время (не старше 10 минут)
                        from datetime import datetime
                        import time
                        tx_datetime = datetime.fromtimestamp(tx_time)
                        time_diff = (datetime.now() - tx_datetime).total_seconds()
                        
                        if time_diff <= 600:  # 10 минут
                            logger.info(f"Найдена подходящая транзакция: {tx_hash}, сумма: {tx_amount}")
                            used_transactions.add(tx_hash)
                            return True, tx_hash
                        else:
                            logger.info(f"Транзакция слишком старая: {time_diff} секунд")
            
            logger.info("Подходящая транзакция не найдена")
            return False, None
            
        except Exception as e:
            logger.error(f"Ошибка проверки платежа: {e}")
            return False, None
    
    async def monitor_payments(self, user_id: int, amount: float, max_attempts: int = 30):
        """
        Мониторинг платежей в реальном времени
        """
        logger.info(f"Начинаем мониторинг платежа {amount} GRAM для пользователя {user_id}")
        
        for attempt in range(max_attempts):
            success, tx_hash = await self.check_payment(amount, user_id)
            
            if success:
                logger.info(f"Платеж подтвержден! Хеш: {tx_hash}")
                return True, tx_hash
            
            # Ждем 10 секунд перед следующей проверкой
            await asyncio.sleep(10)
            
            if attempt % 5 == 0:
                balance = await self.get_balance()
                logger.info(f"Текущий баланс: {balance} TON")
        
        logger.info(f"Мониторинг завершен: платеж не найден")
        return False, None

# ============================================
# ИНИЦИАЛИЗАЦИЯ TON HANDLER
# ============================================

ton_handler = TonHandler(CRYPTO_WALLET, TON_API_KEY)

# ============================================
# КЛАВИАТУРЫ
# ============================================

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💠 Купить нарк0тy 💠", callback_data="buy"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
    )
    return builder.as_markup()

def get_categories_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора категории"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🧂 Соль", callback_data="category_salt"))
    builder.row(InlineKeyboardButton(text="🌿 Каннибиноиды", callback_data="category_cannabis"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_products_keyboard(category: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора продукта по категории"""
    builder = InlineKeyboardBuilder()
    for key, product in PRODUCTS.items():
        if product["category"] == category:
            builder.row(InlineKeyboardButton(
                text=f"{product['emoji']} {product['name']} - {product['price']} GRAM",
                callback_data=f"product_{key}"
            ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_categories"))
    return builder.as_markup()

def get_dosage_keyboard(product_key: str, current_dosage: int, current_price: float) -> InlineKeyboardMarkup:
    """Клавиатура выбора дозировки"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➖", callback_data=f"dosage_down_{product_key}"),
        InlineKeyboardButton(text=f"{current_dosage}г", callback_data="ignore"),
        InlineKeyboardButton(text="➕", callback_data=f"dosage_up_{product_key}")
    )
    builder.row(InlineKeyboardButton(
        text=f"💰 Купить за {current_price:.2f} GRAM", 
        callback_data=f"confirm_purchase_{product_key}"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_products"))
    return builder.as_markup()

def get_admin_ticket_keyboard(ticket_number: int) -> InlineKeyboardMarkup:
    """Клавиатура для админа при новом тикете"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"✅ Принять тикет #{ticket_number}",
        callback_data=f"accept_ticket_{ticket_number}"
    ))
    return builder.as_markup()

def get_admin_chat_keyboard(ticket_number: int) -> InlineKeyboardMarkup:
    """Клавиатура для админа в чате с клиентом"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"❌ Закрыть Тикет #{ticket_number}",
        callback_data=f"close_ticket_{ticket_number}"
    ))
    return builder.as_markup()

def get_user_chat_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для пользователя в чате с админом"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Закрыть чат", callback_data="close_user_chat"))
    return builder.as_markup()

# ============================================
# ОБРАБОТЧИКИ КОМАНД
# ============================================

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start"""
    user_id = message.from_user.id
    
    # Инициализация данных пользователя
    if user_id not in user_data:
        user_data[user_id] = {
            "purchases_today": 0,
            "last_purchase_time": None,
            "cooldown_until": None,
            "balance": 0.0,
            "total_purchases": 0,
            "ticket": None,
            "in_chat": False
        }
    
    # Проверка, находится ли пользователь в чате с админом
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
    await state.clear()

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Скрытая команда для админа"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    if active_tickets:
        text = "📋 Активные тикеты:\n\n"
        for ticket_num, data in active_tickets.items():
            text += f"#{ticket_num} - от {data['user_id']}\n"
            text += f"Товар: {data['product']}, {data['dosage']}г\n"
            text += f"Сумма: {data['amount']} GRAM\n"
            text += f"Время: {data['created_at'].strftime('%H:%M')}\n\n"
        await message.answer(text)
    else:
        await message.answer("Нет активных тикетов.")

# ============================================
# ОБРАБОТЧИКИ INLINE КНОПОК
# ============================================

@dp.callback_query(F.data == "buy")
async def handle_buy(callback: CallbackQuery, state: FSMContext):
    """Обработка кнопки 'Купить наркоту'"""
    user_id = callback.from_user.id
    
    # Проверка КД
    if not check_cooldown(user_id):
        await callback.answer("⚠️ У вас активен кулдаун!", show_alert=True)
        return
    
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_categories_keyboard())
    await callback.answer()
    await state.set_state(PurchaseStates.selecting_product)

@dp.callback_query(F.data == "profile")
async def handle_profile(callback: CallbackQuery):
    """Обработка кнопки 'Профиль'"""
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

@dp.callback_query(F.data == "back_to_main")
async def handle_back_to_main(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
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
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "back_to_categories")
async def handle_back_to_categories(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору категории"""
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_categories_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "back_to_products")
async def handle_back_to_products(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору продукта"""
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_categories_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("category_"))
async def handle_category(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора категории"""
    category = callback.data.split("_")[1]
    category_map = {
        "salt": "соль",
        "cannabis": "каннибиноиды"
    }
    category_name = category_map.get(category, "")
    
    await callback.message.edit_text(
        f"Выберите продукт из категории '{category_name}':",
        reply_markup=get_products_keyboard(category_name)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("product_"))
async def handle_product(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора продукта"""
    product_key = callback.data.split("_")[1]
    product = PRODUCTS.get(product_key)
    
    if not product:
        await callback.answer("Товар не найден!", show_alert=True)
        return
    
    # Инициализация данных для покупки
    await state.update_data(
        product_key=product_key,
        dosage=1,
        price=product["price"]
    )
    
    await callback.message.edit_text(
        f"{product['emoji']} Отлично! Вы покупаете {product['name']}!\n"
        f"Стоимость: {product['price']} GRAM за 1 грамм\n"
        f"Измените дозировку и нажмите 'Купить'",
        reply_markup=get_dosage_keyboard(product_key, 1, product['price'])
    )
    await state.set_state(PurchaseStates.selecting_dosage)
    await callback.answer()

@dp.callback_query(F.data.startswith("dosage_up_"))
async def handle_dosage_up(callback: CallbackQuery, state: FSMContext):
    """Увеличение дозировки"""
    product_key = callback.data.split("_")[2]
    await update_dosage(callback, state, product_key, 1)

@dp.callback_query(F.data.startswith("dosage_down_"))
async def handle_dosage_down(callback: CallbackQuery, state: FSMContext):
    """Уменьшение дозировки"""
    product_key = callback.data.split("_")[2]
    await update_dosage(callback, state, product_key, -1)

async def update_dosage(callback: CallbackQuery, state: FSMContext, product_key: str, delta: int):
    """Обновление дозировки"""
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

@dp.callback_query(F.data.startswith("confirm_purchase_"))
async def handle_confirm_purchase(callback: CallbackQuery, state: FSMContext):
    """Подтверждение покупки с реальной проверкой TON"""
    user_id = callback.from_user.id
    product_key = callback.data.split("_")[2]
    data = await state.get_data()
    
    product = PRODUCTS[product_key]
    dosage = data.get("dosage", 1)
    price = data.get("price", product["price"])
    
    # Проверка лимита покупок
    if not check_purchase_limit(user_id):
        await callback.answer("❌ Достигнут лимит покупок на сегодня!", show_alert=True)
        return
    
    # Сохраняем информацию о платеже
    payment_info = {
        "user_id": user_id,
        "product_key": product_key,
        "product": product["name"],
        "dosage": dosage,
        "amount": price,
        "status": "pending",
        "created_at": datetime.now()
    }
    pending_payments[user_id] = payment_info
    
    # Показываем информацию для оплаты
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
        f"⏳ После отправки нажмите '✅ Проверить оплату'\n"
        f"Система автоматически проверит транзакцию"
    )
    
    await callback.message.edit_text(
        payment_text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_payment")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_products")]
            ]
        ),
        parse_mode="Markdown"
    )
    await state.set_state(PurchaseStates.waiting_for_payment)
    await callback.answer()

@dp.callback_query(F.data == "check_payment")
async def handle_check_payment(callback: CallbackQuery, state: FSMContext):
    """Проверка оплаты через TON API"""
    user_id = callback.from_user.id
    
    if user_id not in pending_payments:
        await callback.answer("❌ Платеж не найден!", show_alert=True)
        return
    
    payment = pending_payments[user_id]
    amount = payment["amount"]
    product_key = payment["product_key"]
    product = PRODUCTS[product_key]
    
    # Отправляем сообщение о начале проверки
    await callback.message.edit_text(
        "⏳ Проверка оплаты...\n"
        "Пожалуйста, подождите несколько секунд."
    )
    
    # Проверяем платеж
    success, tx_hash = await ton_handler.check_payment(amount, user_id)
    
    if success:
        # Завершаем покупку
        await complete_purchase(callback, state, user_id, product, payment["dosage"], amount, tx_hash)
    else:
        # Даем еще одну попытку с мониторингом
        await callback.message.edit_text(
            f"⏳ Оплата не найдена.\n"
            f"Начинаю мониторинг транзакций...\n"
            f"Система будет проверять платеж в течение 5 минут.\n\n"
            f"Убедитесь, что вы отправили ровно {amount:.2f} GRAM\n"
            f"на кошелек:\n"
            f"`{CRYPTO_WALLET}`",
            parse_mode="Markdown"
        )
        
        # Запускаем мониторинг в фоне
        success, tx_hash = await ton_handler.monitor_payments(user_id, amount, max_attempts=30)
        
        if success:
            await complete_purchase(callback, state, user_id, product, payment["dosage"], amount, tx_hash)
        else:
            # Неудача
            await callback.message.edit_text(
                f"❌ Оплата не найдена.\n"
                f"Пожалуйста, попробуйте снова или свяжитесь с поддержкой.\n\n"
                f"Проверьте, что вы отправили ровно {amount:.2f} GRAM\n"
                f"на кошелек: `{CRYPTO_WALLET}`",
                parse_mode="Markdown"
            )
            # Очищаем данные о платеже
            if user_id in pending_payments:
                del pending_payments[user_id]

async def complete_purchase(callback: CallbackQuery, state: FSMContext, user_id: int, 
                            product: Dict, dosage: int, amount: float, tx_hash: str = None):
    """Завершение покупки с созданием тикета"""
    
    # Обновление данных пользователя
    if user_id not in user_data:
        user_data[user_id] = {"purchases_today": 0, "total_purchases": 0, "balance": 0}
    
    user_data[user_id]["purchases_today"] += 1
    user_data[user_id]["total_purchases"] += 1
    user_data[user_id]["last_purchase_time"] = datetime.now()
    
    # Установка КД
    if user_data[user_id]["purchases_today"] >= 2:
        user_data[user_id]["cooldown_until"] = datetime.now() + timedelta(hours=24)
    else:
        user_data[user_id]["cooldown_until"] = datetime.now() + timedelta(hours=5)
    
    # Генерация тикета
    ticket_number = random.randint(1, 150000)
    user_data[user_id]["ticket"] = ticket_number
    
    # Сохранение тикета
    active_tickets[ticket_number] = {
        "user_id": user_id,
        "product": product["name"],
        "dosage": dosage,
        "amount": amount,
        "tx_hash": tx_hash,
        "created_at": datetime.now()
    }
    admin_tickets[user_id] = ticket_number
    
    # Удаление из ожидающих платежей
    if user_id in pending_payments:
        del pending_payments[user_id]
    
    # Очистка состояния
    await state.clear()
    
    # Отправка сообщения пользователю
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
    
    # Уведомление админа
    admin_message = (
        f"🔔 НОВАЯ ПОКУПКА!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🎫 Тикет: #{ticket_number}\n"
        f"👤 Пользователь: {user_id}\n"
        f"📦 Товар: {product['name']}\n"
        f"⚖️ Дозировка: {dosage}г\n"
        f"💰 Сумма: {amount:.2f} GRAM\n"
        f"🔗 Хеш транзакции: {tx_hash or 'Не указан'}\n"
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

@dp.callback_query(F.data.startswith("accept_ticket_"))
async def handle_accept_ticket(callback: CallbackQuery):
    """Принятие тикета администратором"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    ticket_number = int(callback.data.split("_")[2])
    
    if ticket_number not in active_tickets:
        await callback.answer("❌ Тикет не найден!", show_alert=True)
        return
    
    ticket = active_tickets[ticket_number]
    user_id = ticket["user_id"]
    
    # Отметка, что пользователь в чате
    if user_id in user_data:
        user_data[user_id]["in_chat"] = True
    
    # Создание чата
    await callback.message.edit_text(
        f"✅ Тикет #{ticket_number} ПРИНЯТ!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👤 Пользователь: {user_id}\n"
        f"📦 Товар: {ticket['product']}\n"
        f"⚖️ Дозировка: {ticket['dosage']}г\n"
        f"💰 Сумма: {ticket['amount']:.2f} GRAM\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💬 Теперь вы можете общаться с клиентом.\n"
        f"Отправляйте текст, фото или геолокацию.\n"
        f"━━━━━━━━━━━━━━━━",
        reply_markup=get_admin_chat_keyboard(ticket_number)
    )
    
    # Уведомление пользователя
    await bot.send_message(
        user_id,
        f"✅ Продавец принял ваш тикет #{ticket_number}!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💬 Теперь вы можете общаться с продавцом через этого бота.\n"
        f"Отправляйте сообщения, фото или геолокацию.\n"
        f"━━━━━━━━━━━━━━━━",
        reply_markup=get_user_chat_keyboard()
    )
    
    await callback.answer("✅ Тикет принят!")

@dp.callback_query(F.data.startswith("close_ticket_"))
async def handle_close_ticket(callback: CallbackQuery):
    """Закрытие тикета администратором"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    ticket_number = int(callback.data.split("_")[2])
    
    if ticket_number not in active_tickets:
        await callback.answer("❌ Тикет не найден!", show_alert=True)
        return
    
    ticket = active_tickets[ticket_number]
    user_id = ticket["user_id"]
    
    # Обновление данных пользователя
    if user_id in user_data:
        user_data[user_id]["in_chat"] = False
        user_data[user_id]["ticket"] = None
        # Увеличиваем счетчик покупок в профиле
        user_data[user_id]["total_purchases"] += 1
    
    # Удаление тикета
    del active_tickets[ticket_number]
    if user_id in admin_tickets:
        del admin_tickets[user_id]
    
    # Уведомление пользователя
    try:
        await bot.send_message(
            user_id,
            f"❌ Тикет #{ticket_number} закрыт продавцом.\n"
            f"Спасибо за покупку! Возвращайтесь снова. 🌟"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления пользователю: {e}")
    
    await callback.message.edit_text(
        f"❌ Тикет #{ticket_number} ЗАКРЫТ!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Покупка завершена.\n"
        f"Данные сохранены в профиле пользователя.\n"
        f"━━━━━━━━━━━━━━━━"
    )
    
    await callback.answer("✅ Тикет закрыт!")

@dp.callback_query(F.data == "close_user_chat")
async def handle_close_user_chat(callback: CallbackQuery):
    """Закрытие чата пользователем"""
    user_id = callback.from_user.id
    
    if user_id not in user_data or not user_data[user_id].get("in_chat", False):
        await callback.answer("❌ У вас нет активного чата!", show_alert=True)
        return
    
    # Проверка, есть ли активный тикет
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
# ОБРАБОТКА СООБЩЕНИЙ В ЧАТЕ
# ============================================

@dp.message(F.text | F.photo | F.location)
async def handle_chat_messages(message: Message, state: FSMContext):
    """Обработка сообщений в чате между админом и пользователем"""
    user_id = message.from_user.id
    
    # Если сообщение от админа
    if user_id == ADMIN_ID:
        # Найти пользователя по активному тикету
        target_user = None
        target_ticket = None
        
        for ticket_num, ticket in active_tickets.items():
            if ticket["user_id"] == ADMIN_ID:
                continue
            # Проверяем, есть ли у админа открытый чат с этим пользователем
            if ticket["user_id"] in admin_tickets and admin_tickets[ticket["user_id"]] == ticket_num:
                target_user = ticket["user_id"]
                target_ticket = ticket_num
                break
        
        if not target_user:
            await message.answer("❌ Нет активного чата с пользователем. Примите тикет сначала.")
            return
        
        # Пересылка сообщения пользователю
        try:
            if message.text:
                await bot.send_message(target_user, f"🛒 Продавец: {message.text}")
            elif message.photo:
                await bot.send_photo(
                    target_user, 
                    message.photo[-1].file_id, 
                    caption=f"🛒 Продавец: {message.caption or ''}"
                )
            elif message.location:
                await bot.send_location(
                    target_user, 
                    message.location.latitude, 
                    message.location.longitude
                )
                await bot.send_message(target_user, "📍 Продавец отправил геолокацию")
            
            await message.answer("✅ Сообщение отправлено пользователю.")
            
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю: {e}")
            await message.answer("❌ Ошибка отправки сообщения")
    
    # Если сообщение от пользователя
    else:
        # Проверка, находится ли пользователь в чате
        if user_id not in user_data or not user_data[user_id].get("in_chat", False):
            await message.answer("❌ У вас нет активного чата. Используйте главное меню.")
            return
        
        # Пересылка сообщения админу
        ticket_number = user_data[user_id].get("ticket")
        if not ticket_number or ticket_number not in active_tickets:
            await message.answer("❌ Тикет не найден. Обратитесь в главное меню.")
            return
        
        try:
            if message.text:
                await bot.send_message(
                    ADMIN_ID, 
                    f"💬 От пользователя #{ticket_number}:\n{message.text}"
                )
            elif message.photo:
                await bot.send_photo(
                    ADMIN_ID, 
                    message.photo[-1].file_id, 
                    caption=f"💬 От пользователя #{ticket_number}:\n{message.caption or ''}"
                )
            elif message.location:
                await bot.send_location(
                    ADMIN_ID, 
                    message.location.latitude, 
                    message.location.longitude
                )
                await bot.send_message(
                    ADMIN_ID, 
                    f"📍 Геолокация от пользователя #{ticket_number}"
                )
            
            await message.answer("✅ Сообщение отправлено продавцу.")
            
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения админу: {e}")
            await message.answer("❌ Ошибка отправки сообщения")

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def check_cooldown(user_id: int) -> bool:
    """Проверка КД на покупки"""
    if user_id not in user_data:
        return True
    
    cooldown_until = user_data[user_id].get("cooldown_until")
    if not cooldown_until:
        return True
    
    # Если КД прошел, сбрасываем счетчик покупок
    if datetime.now() >= cooldown_until:
        user_data[user_id]["purchases_today"] = 0
        user_data[user_id]["cooldown_until"] = None
        return True
    
    return False

def check_purchase_limit(user_id: int) -> bool:
    """Проверка лимита покупок (2 в день)"""
    if user_id not in user_data:
        return True
    
    purchases_today = user_data[user_id].get("purchases_today", 0)
    return purchases_today < 2

# ============================================
# ЗАПУСК БОТА
# ============================================

async def main():
    """Запуск бота"""
    logger.info("🚀 Бот запускается...")
    
    # Проверка подключения к TON
    try:
        balance = await ton_handler.get_balance()
        logger.info(f"💰 Баланс кошелька: {balance} TON")
        logger.info(f"🔗 Кошелек: {CRYPTO_WALLET}")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к TON: {e}")
    
    logger.info("✅ Бот готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
