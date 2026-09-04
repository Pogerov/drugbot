import logging
import random
import hashlib
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.utils import executor

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

BOT_TOKEN = "8997465806:AAEPCdj2o2GmeRlnBzUJTG2qYDTwxt0ARXk"
ADMIN_ID = 7753887058
BOT_USERNAME = "dfsddfagas_bot"

# ============================================
# КУРСЫ ВАЛЮТ (1 GRAM = X)
# ============================================

EXCHANGE_RATES = {
    "GRAM": 1.0,
    "USDT": 1.0,
    "BTC": 0.00000012,
}

# ============================================
# КОШЕЛЬКИ
# ============================================

CRYPTO_WALLETS = {
    "GRAM": {
        "address": "UQDRRRGutl_ccP25XcwbOK-RN2UXuvE1_GFoerlaIDvmwO7I",
        "emoji": "💎",
        "network": "TON"
    },
    "USDT": {
        "address": "TNdRJZQSTss4JnnP8LoaRQrcA7SbmGTijk",
        "emoji": "🪙",
        "network": "TRC20 (Tether)"
    },
    "BTC": {
        "address": "bc1qc6nuwczmtgxeql72wzsxsyctmhp3h4430emy9z",
        "emoji": "₿",
        "network": "Bitcoin"
    }
}

# ============================================
# БАЗА ДАННЫХ ДЛЯ АКТИВНЫХ ЧАТОВ
# ============================================

def init_chat_db():
    conn = sqlite3.connect('active_chats.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS active_chats (
            admin_id INTEGER PRIMARY KEY,
            ticket_number INTEGER,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_active_chat(admin_id: int, ticket_number: int, user_id: int):
    conn = sqlite3.connect('active_chats.db')
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO active_chats (admin_id, ticket_number, user_id)
        VALUES (?, ?, ?)
    ''', (admin_id, ticket_number, user_id))
    conn.commit()
    conn.close()

def get_active_chat(admin_id: int):
    conn = sqlite3.connect('active_chats.db')
    c = conn.cursor()
    c.execute('''
        SELECT ticket_number, user_id FROM active_chats WHERE admin_id = ?
    ''', (admin_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'ticket_number': row[0], 'user_id': row[1]}
    return None

def clear_active_chat(admin_id: int):
    conn = sqlite3.connect('active_chats.db')
    c = conn.cursor()
    c.execute('DELETE FROM active_chats WHERE admin_id = ?', (admin_id,))
    conn.commit()
    conn.close()

# Инициализация БД
init_chat_db()

# ============================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# БОТ
# ============================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# ============================================
# LEET-ЦЕНЗУРА
# ============================================

DRUG_LEET = {
    "мефедрон": "MeF",
    "a-pvp": "a-PvP",
    "мдвп": "MDVP",
    "скорость": "Ck0p0ctb",
    "кристаллы": "KpucTaLLbl",
    "экстази": "3kcta3u",
    "гашиш": "GaWuw",
    "марихуанна": "MapuxyaHHa",
    "шишки": "Wuwku",
    "спайс": "Cnauc",
    "героин": "Gep0uH",
    "метадон": "MeTaDoH",
    "трамадол": "TpamaDoL",
    "фентанил": "FeHTaHuL",
    "кодеин": "KoDeuH",
    "морфин": "MopHuH",
    "лсд": "LSD",
    "грибы": "Gpu6bl",
    "dmt": "DMT",
    "мескалин": "MeCkaLuH",
    "2c-b": "2C-B",
    "кетамин": "KeTaMuH",
    "pcp": "PCP",
    "масло thc": "MacLo THC",
    "каннибиноиды": "KaHHa6uHouDu",
    "опиоиды": "OnoUoDu",
    "психоделики": "NcuXoDeLuKu",
    "диссоциативы": "DuccoUaTuBu",
    "соль": "CoLb",
    "наркотик": "HaPk0TuK",
    "наркота": "HaPk0Ta",
}

def censor_drugs(text: str) -> str:
    result = text
    for word, leet in DRUG_LEET.items():
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        result = pattern.sub(leet, result)
    return result

# ============================================
# ДАННЫЕ
# ============================================

class PurchaseStates(StatesGroup):
    selecting_category = State()

PRODUCTS = {
    "меф": {"name": "Мефедрон", "price": 15, "category": "соль", "emoji": "💎"},
    "a-pvp": {"name": "a-PvP", "price": 9, "category": "соль", "emoji": "⚗️"},
    "мдвп": {"name": "МДВП", "price": 13, "category": "соль", "emoji": "🧪"},
    "скорость": {"name": "Скорость", "price": 7, "category": "соль", "emoji": "⚡"},
    "кристаллы": {"name": "Кристаллы", "price": 20, "category": "соль", "emoji": "💠"},
    "экстази": {"name": "Экстази", "price": 18, "category": "соль", "emoji": "🎯"},
    "гашиш": {"name": "Гашиш", "price": 12, "category": "каннибиноиды", "emoji": "🌿"},
    "марихуанна": {"name": "Марихуанна", "price": 8, "category": "каннибиноиды", "emoji": "🍃"},
    "шишки": {"name": "Шишки", "price": 14, "category": "каннибиноиды", "emoji": "🌲"},
    "масло": {"name": "Масло THC", "price": 25, "category": "каннибиноиды", "emoji": "💧"},
    "спайс": {"name": "Спайс", "price": 10, "category": "каннибиноиды", "emoji": "🔥"},
    "героин": {"name": "Героин", "price": 30, "category": "опиоиды", "emoji": "☠️"},
    "метадон": {"name": "Метадон", "price": 22, "category": "опиоиды", "emoji": "💊"},
    "трамадол": {"name": "Трамадол", "price": 11, "category": "опиоиды", "emoji": "💉"},
    "фентанил": {"name": "Фентанил", "price": 40, "category": "опиоиды", "emoji": "⚰️"},
    "кодеин": {"name": "Кодеин", "price": 9, "category": "опиоиды", "emoji": "🍬"},
    "морфин": {"name": "Морфин", "price": 27, "category": "опиоиды", "emoji": "🏥"},
    "лсд": {"name": "ЛСД", "price": 16, "category": "психоделики", "emoji": "🌈"},
    "грибы": {"name": "Грибы", "price": 12, "category": "психоделики", "emoji": "🍄"},
    "dmt": {"name": "DMT", "price": 35, "category": "психоделики", "emoji": "👁️"},
    "мескалин": {"name": "Мескалин", "price": 28, "category": "психоделики", "emoji": "🌵"},
    "2cb": {"name": "2C-B", "price": 20, "category": "психоделики", "emoji": "🎨"},
    "кетамин": {"name": "Кетамин", "price": 17, "category": "диссоциативы", "emoji": "🐴"},
    "pcp": {"name": "PCP", "price": 19, "category": "диссоциативы", "emoji": "🧊"},
}

user_data: Dict[int, Dict] = {}
active_tickets: Dict[int, Dict] = {}
referral_data: Dict[int, Dict] = {}

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def get_user_currency(user_id: int) -> str:
    if user_id not in user_data:
        return "GRAM"
    return user_data[user_id].get("currency", "GRAM")

def set_user_currency(user_id: int, currency: str):
    if user_id not in user_data:
        auto_register(user_id)
    user_data[user_id]["currency"] = currency

def convert_price(price_in_gram: float, currency: str) -> float:
    rate = EXCHANGE_RATES.get(currency, 1.0)
    return round(price_in_gram * rate, 8)

def format_price(price: float, currency: str) -> str:
    if currency == "BTC":
        return f"{price:.8f}"
    else:
        return f"{price:.2f}"

# ============================================
# КЛАВИАТУРЫ
# ============================================

def get_main_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton(text="💠 Купить 💠", callback_data="buy"))
    keyboard.add(InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    keyboard.add(InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="referral"))
    keyboard.add(InlineKeyboardButton(text="💱 Выбрать валюту", callback_data="change_currency"))
    return keyboard

def get_currency_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton(text="💎 GRAM (TON)", callback_data="set_currency_GRAM"),
        InlineKeyboardButton(text="🪙 USDT (TRC20)", callback_data="set_currency_USDT"),
        InlineKeyboardButton(text="₿ BTC (Bitcoin)", callback_data="set_currency_BTC"),
    )
    keyboard.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return keyboard

def get_categories_keyboard(user_id: int):
    keyboard = InlineKeyboardMarkup(row_width=1)
    currency = get_user_currency(user_id)
    keyboard.add(
        InlineKeyboardButton(text=f"🧂 Соль ({currency})", callback_data="category_salt"),
        InlineKeyboardButton(text=f"🌿 Каннабиноиды ({currency})", callback_data="category_cannabis"),
        InlineKeyboardButton(text=f"☠️ Опиоиды ({currency})", callback_data="category_opioids"),
        InlineKeyboardButton(text=f"🌈 Психоделики ({currency})", callback_data="category_psychedelics"),
        InlineKeyboardButton(text=f"🐴 Диссоциативы ({currency})", callback_data="category_dissociatives"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
    )
    return keyboard

def get_products_keyboard(category: str, user_id: int):
    keyboard = InlineKeyboardMarkup(row_width=1)
    currency = get_user_currency(user_id)
    
    for key, product in PRODUCTS.items():
        if product["category"] == category:
            leet_name = censor_drugs(product['name'])
            price_in_currency = convert_price(product['price'], currency)
            price_str = format_price(price_in_currency, currency)
            keyboard.add(InlineKeyboardButton(
                text=f"{product['emoji']} {leet_name} - {price_str} {currency}",
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

def get_back_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return keyboard

# ============================================
# РЕФЕРАЛЬНАЯ СИСТЕМА
# ============================================

def generate_referral_link(user_id: int) -> str:
    ref_code = hashlib.md5(str(user_id).encode()).hexdigest()[:8]
    return f"https://t.me/{BOT_USERNAME}?start=ref_{ref_code}"

def get_user_id_from_ref_code(ref_code: str) -> Optional[int]:
    for uid, data in referral_data.items():
        if data.get("ref_code") == ref_code:
            return uid
    return None

def auto_register(user_id: int):
    if user_id not in user_data:
        user_data[user_id] = {
            "purchases_today": 0,
            "cooldown_until": None,
            "balance": 0.0,
            "total_purchases": 0,
            "ticket": None,
            "in_chat": False,
            "currency": "GRAM",
            "ref_code": hashlib.md5(str(user_id).encode()).hexdigest()[:8],
            "invited_users": 0
        }
        referral_data[user_id] = {
            "ref_code": user_data[user_id]["ref_code"],
            "ref_link": generate_referral_link(user_id),
            "invited_users": 0
        }

async def delete_chat_messages(user_id: int):
    try:
        deleted_count = 0
        for attempt in range(2):
            try:
                messages = await bot.get_chat_history(chat_id=user_id, limit=100)
                if not messages:
                    break
                
                for msg in messages:
                    try:
                        await bot.delete_message(chat_id=user_id, message_id=msg.message_id)
                        deleted_count += 1
                    except:
                        continue
                
                if len(messages) < 100:
                    break
                
            except:
                break
        
        logger.info(f"✅ Удалено {deleted_count} сообщений у пользователя {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка при удалении: {e}")

# ============================================
# ОБРАБОТЧИКИ
# ============================================

@dp.message_handler(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    args = message.get_args()
    
    auto_register(user_id)
    
    if args and args.startswith("ref_"):
        ref_code = args[4:]
        inviter_id = get_user_id_from_ref_code(ref_code)
        
        if inviter_id and inviter_id != user_id:
            if inviter_id in user_data:
                user_data[inviter_id]["invited_users"] += 1
                referral_data[inviter_id]["invited_users"] += 1
                
                await bot.send_message(
                    inviter_id,
                    f"👤 Пользователь {user_id} перешел по вашей реферальной ссылке!"
                )
            
            await message.answer("✅ Вы перешли по реферальной ссылке!")
    
    if user_data[user_id].get("in_chat", False):
        await message.answer("Вы находитесь в активном чате с продавцом.")
        return
    
    currency = get_user_currency(user_id)
    
    welcome_text = (
        f"Привет, это бот для покупок.\n"
        f"Здесь есть ассортимент товаров по разным категориям.\n"
        f"После выбора товара создается тикет, и вы общаетесь с продавцом напрямую.\n"
        f"Все цены отображаются в валюте: {currency}\n"
        f"Вы можете сменить валюту через кнопку '💱 Выбрать валюту'.\n"
        f"Всех благ и хороших покупок."
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "change_currency")
async def handle_change_currency(callback: CallbackQuery):
    await callback.message.edit_text(
        "💱 Выберите валюту для отображения цен:\n\n"
        "Все цены будут пересчитаны автоматически.",
        reply_markup=get_currency_keyboard()
    )
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("set_currency_"))
async def handle_set_currency(callback: CallbackQuery):
    user_id = callback.from_user.id
    currency = callback.data.split("_")[2]
    
    set_user_currency(user_id, currency)
    await callback.answer(f"✅ Валюта изменена на {currency}")
    
    welcome_text = (
        f"Привет, это бот для покупок.\n"
        f"Здесь есть ассортимент товаров по разным категориям.\n"
        f"После выбора товара создается тикет, и вы общаетесь с продавцом напрямую.\n"
        f"Все цены отображаются в валюте: {currency}\n"
        f"Вы можете сменить валюту через кнопку '💱 Выбрать валюту'.\n"
        f"Всех благ и хороших покупок."
    )
    await callback.message.edit_text(welcome_text, reply_markup=get_main_keyboard())

@dp.callback_query_handler(lambda c: c.data == "buy")
async def handle_buy(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    auto_register(user_id)
    
    if not check_cooldown(user_id):
        await callback.answer("⚠️ У вас активен кулдаун!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "Выберите категорию:",
        reply_markup=get_categories_keyboard(user_id)
    )
    await callback.answer()
    await state.set_state(PurchaseStates.selecting_category)

@dp.callback_query_handler(lambda c: c.data == "profile")
async def handle_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    auto_register(user_id)
    
    data = user_data.get(user_id, {"purchases_today": 0, "total_purchases": 0, "balance": 0})
    currency = get_user_currency(user_id)
    
    profile_text = (
        f"👤 Ваш профиль:\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📦 Покупки сегодня: {data.get('purchases_today', 0)}/2\n"
        f"🔄 Всего покупок: {data.get('total_purchases', 0)}\n"
        f"💰 Баланс: {data.get('balance', 0):.2f} {currency}\n"
        f"👥 Приглашено: {data.get('invited_users', 0)}\n"
        f"🆔 ID: {user_id}\n"
        f"💱 Валюта: {currency}\n"
        f"━━━━━━━━━━━━━━━━"
    )
    
    await callback.message.edit_text(profile_text, reply_markup=get_back_keyboard())
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "referral")
async def handle_referral(callback: CallbackQuery):
    user_id = callback.from_user.id
    auto_register(user_id)
    
    ref_link = generate_referral_link(user_id)
    invited = user_data[user_id].get("invited_users", 0)
    
    text = (
        f"🔗 Ваша реферальная ссылка:\n"
        f"`{ref_link}`\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👤 Приглашено: {invited} человек\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📤 Отправьте эту ссылку друзьям!"
    )
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "back_to_main")
async def handle_back_to_main(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_data[user_id].get("in_chat", False):
        await callback.answer("⚠️ Вы не можете выйти из чата!", show_alert=True)
        return
    
    currency = get_user_currency(user_id)
    
    welcome_text = (
        f"Привет, это бот для покупок.\n"
        f"Здесь есть ассортимент товаров по разным категориям.\n"
        f"После выбора товара создается тикет, и вы общаетесь с продавцом напрямую.\n"
        f"Все цены отображаются в валюте: {currency}\n"
        f"Вы можете сменить валюту через кнопку '💱 Выбрать валюту'.\n"
        f"Всех благ и хороших покупок."
    )
    await callback.message.edit_text(welcome_text, reply_markup=get_main_keyboard())
    await state.finish()
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "back_to_categories")
async def handle_back_to_categories(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.edit_text(
        "Выберите категорию:",
        reply_markup=get_categories_keyboard(user_id)
    )
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("category_"))
async def handle_category(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    category = callback.data.split("_")[1]
    category_map = {
        "salt": "соль", 
        "cannabis": "каннибиноиды",
        "opioids": "опиоиды",
        "psychedelics": "психоделики",
        "dissociatives": "диссоциативы"
    }
    category_name = category_map.get(category, "")
    
    censored_category = censor_drugs(category_name)
    
    await callback.message.edit_text(
        f"Выберите продукт из категории '{censored_category}':",
        reply_markup=get_products_keyboard(category_name, user_id)
    )
    await callback.answer()

# ============================================
# ВЫБОР ТОВАРА → СОЗДАНИЕ ТИКЕТА
# ============================================

@dp.callback_query_handler(lambda c: c.data.startswith("product_"))
async def handle_product(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    auto_register(user_id)
    
    product_key = callback.data.split("_")[1]
    product = PRODUCTS.get(product_key)
    
    if not product:
        await callback.answer("Товар не найден!", show_alert=True)
        return
    
    if not check_cooldown(user_id):
        await callback.answer("⚠️ У вас активен кулдаун!", show_alert=True)
        return
    
    if not check_purchase_limit(user_id):
        await callback.answer("❌ Достигнут лимит покупок на сегодня!", show_alert=True)
        return
    
    # Создаём тикет
    ticket_number = random.randint(1, 150000)
    currency = get_user_currency(user_id)
    
    if user_id not in user_data:
        user_data[user_id] = {"purchases_today": 0, "total_purchases": 0, "balance": 0}
    
    user_data[user_id]["purchases_today"] += 1
    user_data[user_id]["total_purchases"] += 1
    user_data[user_id]["ticket"] = ticket_number
    user_data[user_id]["in_chat"] = True
    
    if user_data[user_id]["purchases_today"] >= 2:
        user_data[user_id]["cooldown_until"] = datetime.now() + timedelta(hours=24)
    else:
        user_data[user_id]["cooldown_until"] = datetime.now() + timedelta(hours=5)
    
    price_in_gram = product['price']
    price_in_currency = convert_price(price_in_gram, currency)
    price_str = format_price(price_in_currency, currency)
    
    wallet = CRYPTO_WALLETS.get(currency)
    
    active_tickets[ticket_number] = {
        "user_id": user_id,
        "product": product["name"],
        "price": price_in_gram,
        "currency": currency,
        "created_at": datetime.now()
    }
    
    await state.finish()
    
    leet_name = censor_drugs(product['name'])
    
    await callback.message.edit_text(
        f"✅ Вы выбрали {product['emoji']} {leet_name}!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🎫 Ваш тикет создан! #{ticket_number}\n"
        f"💰 Стоимость: {price_str} {currency}\n"
        f"📤 Кошелёк: `{wallet['address']}`\n"
        f"📡 Сеть: {wallet['network']}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"⏳ Переведите точную сумму и ожидайте, продавец свяжется с вами!",
        parse_mode="Markdown"
    )
    
    admin_message = (
        f"🔔 НОВАЯ ПОКУПКА!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🎫 Тикет: #{ticket_number}\n"
        f"👤 Пользователь: {user_id}\n"
        f"📦 Товар: {product['name']}\n"
        f"💰 Сумма: {price_str} {currency}\n"
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
# АДМИН (С БАЗОЙ ДАННЫХ)
# ============================================

@dp.callback_query_handler(lambda c: c.data.startswith("accept_ticket_"))
async def handle_accept_ticket(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    ticket_number = int(callback.data.split("_")[2])
    
    if ticket_number not in active_tickets:
        await callback.answer("❌ Тикет не найден!", show_alert=True)
        return
    
    # Проверяем, есть ли уже активный чат
    current = get_active_chat(ADMIN_ID)
    if current:
        await callback.answer(f"❌ Активен чат #{current['ticket_number']}!", show_alert=True)
        return
    
    ticket = active_tickets[ticket_number]
    user_id = ticket["user_id"]
    
    # СОХРАНЯЕМ В БАЗУ
    save_active_chat(ADMIN_ID, ticket_number, user_id)
    
    if user_id in user_data:
        user_data[user_id]["in_chat"] = True
    
    await callback.answer("✅ Тикет принят!")
    
    await callback.message.edit_text(
        f"✅ Тикет #{ticket_number} ПРИНЯТ!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👤 Пользователь: {user_id}\n"
        f"📦 Товар: {ticket['product']}\n"
        f"💰 Сумма: {ticket['price']} GRAM\n"
        f"💳 Валюта: {ticket.get('currency', 'GRAM')}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💬 Теперь вы общаетесь с клиентом.",
        reply_markup=get_admin_chat_keyboard(ticket_number)
    )
    
    await bot.send_message(
        user_id,
        f"✅ Продавец принял ваш тикет #{ticket_number}!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💬 Теперь вы можете общаться с продавцом."
    )

@dp.callback_query_handler(lambda c: c.data.startswith("close_ticket_"))
async def handle_close_ticket(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа!", show_alert=True)
        return
    
    ticket_number = int(callback.data.split("_")[2])
    
    # Проверяем, что это активный чат
    current = get_active_chat(ADMIN_ID)
    if not current or current['ticket_number'] != ticket_number:
        await callback.answer("❌ Тикет не активен!", show_alert=True)
        return
    
    if ticket_number not in active_tickets:
        await callback.answer("❌ Тикет не найден!", show_alert=True)
        return
    
    ticket = active_tickets[ticket_number]
    user_id = ticket["user_id"]
    
    await callback.answer("✅ Тикет закрывается...")
    
    try:
        await delete_chat_messages(user_id)
        logger.info(f"✅ Сообщения удалены у пользователя {user_id}")
    except Exception as e:
        logger.error(f"Ошибка удаления сообщений у пользователя: {e}")
    
    if user_id in user_data:
        user_data[user_id]["in_chat"] = False
        user_data[user_id]["ticket"] = None
        user_data[user_id]["total_purchases"] += 1
    
    del active_tickets[ticket_number]
    
    # УДАЛЯЕМ ИЗ БАЗЫ
    clear_active_chat(ADMIN_ID)
    
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

# ============================================
# ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ
# ============================================

@dp.message_handler(content_types=['text'])
async def handle_all_text_messages(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text
    
    if user_id == ADMIN_ID:
        # Проверяем активный чат из БАЗЫ
        current = get_active_chat(ADMIN_ID)
        if current and current['ticket_number'] in active_tickets:
            try:
                await bot.send_message(current['user_id'], f"🛒 Продавец: {text}")
                await message.answer(f"✅ Отправлено (тикет #{current['ticket_number']})")
                return
            except Exception as e:
                logger.error(f"Ошибка отправки админом: {e}")
                await message.answer("❌ Ошибка отправки")
                return
        
        await message.answer("❌ Нет активного чата. Примите тикет сначала.")
        return
    
    ticket_number = user_data.get(user_id, {}).get("ticket")
    in_chat = user_data.get(user_id, {}).get("in_chat", False)
    
    if ticket_number and ticket_number in active_tickets and in_chat:
        try:
            await bot.send_message(ADMIN_ID, f"💬 От #{ticket_number}:\n{text}")
            await message.answer("✅ Отправлено продавцу.")
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await message.answer("❌ Ошибка отправки")
        return
    
    await message.answer("❌ Чтобы общаться с продавцом, сначала сделайте покупку через кнопку '💠 Купить'.")

# ============================================
# ВСПОМОГАТЕЛЬНЫЕ
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
    logger.info("🚀 Бот запущен!")
    logger.info(f"👤 Админ: {ADMIN_ID}")
    logger.info(f"🤖 Бот: @{BOT_USERNAME}")
    logger.info("✅ Бот готов!")

if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
