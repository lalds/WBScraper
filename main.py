import logging
import asyncio
import os
import random
from contextlib import suppress
from aiogram.exceptions import TelegramBadRequest
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from config import BOT_TOKEN, PROXY_FILE
from services.wb_api import WBApi
from services.core import ProductFilter
from categories import CATEGORIES

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальные настройки
USE_PROXY = True
USE_BLACKLIST = True
BLACKLIST_FILE = "seen_sellers.txt"

def load_blacklist():
    if not os.path.exists(BLACKLIST_FILE):
        return set()
    with open(BLACKLIST_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_to_blacklist(supplier_ids):
    with open(BLACKLIST_FILE, "a") as f:
        for sid in supplier_ids:
            f.write(f"{sid}\n")

def get_main_menu():
    kb = [
        [InlineKeyboardButton(text="🔎 Поиск по запросу", callback_data="manual_search")],
        [InlineKeyboardButton(text="📂 Категории", callback_data="categories")],
        [InlineKeyboardButton(text="⚙️ Настройки (Прокси)", callback_data="settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_settings_menu():
    proxy_status = "✅ ВКЛ" if USE_PROXY else "❌ ВЫКЛ"
    black_status = "✅ ВКЛ" if USE_BLACKLIST else "❌ ВЫКЛ"
    kb = [
        [InlineKeyboardButton(text=f"Прокси: {proxy_status}", callback_data="toggle_proxy")],
        [InlineKeyboardButton(text=f"Черный список: {black_status}", callback_data="toggle_blacklist")],
        [InlineKeyboardButton(text="� Очистить историю", callback_data="clear_blacklist")],
        [InlineKeyboardButton(text="�🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_categories_menu():
    kb = []
    for key, data in CATEGORIES.items():
        kb.append([InlineKeyboardButton(text=data["name"], callback_data=f"cat_{key}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_items_menu(cat_key):
    items = CATEGORIES.get(cat_key, {}).get("queries", [])
    kb = []
    for item in items:
        # Обрезаем длинные callback_data если нужно, но тут запросы короткие
        cb_data = f"search_{item[:20]}" 
        kb.append([InlineKeyboardButton(text=item, callback_data=cb_data)])
    kb.append([InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="categories")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def format_age(months):
    """Превращает месяцы в читаемую строку."""
    if not months: return "Новичок"
    years = months // 12
    m = months % 12
    res = []
    if years > 0:
        res.append(f"{years}г.")
    if m > 0:
        res.append(f"{m} мес.")
    return " ".join(res) if res else "Менее месяца"

def generate_html_report(query, products):
    """Генерирует красивый HTML-отчет с упором на новых продавцов."""
    items_html = ""
    for i, p in enumerate(products, 1):
        nm_id = p['id']
        vol = nm_id // 100000
        part = nm_id // 1000
        basket = (nm_id // 1000000) % 15 + 1
        basket_str = f"{basket:02d}"
        
        img_url = f"https://basket-{basket_str}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/images/big/1.webp"
        seller_url = f"https://www.wildberries.ru/seller/{p['supplierId']}"
        product_url = f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"
        
        # Получаем данные из словаря
        legal = p.get('legal_info', {})
        seller_name = p.get('seller_name', 'Имя не определено')
        age_val = p.get('age_months', -1)
        age_type = p.get('age_type', 'unknown')
        
        # Бейдж возраста и описание
        if age_val != -1:
            age_text = format_age(age_val)
            if age_type == 'exact':
                age_class = "age-new" if age_val <= 12 else "age-young"
                badge_html = f'<span class="badge {age_class}">{age_text} на WB</span>'
                meta_age = f"Стаж: {age_text} (точно)"
            else:
                # Для эвристики используем другой стиль
                badge_html = f'<span class="badge age-young" style="background:#6c757d">~{age_text} на WB</span>'
                meta_age = f"Стаж: ~{age_text} (оценка по NM/отзывам)"
        else:
            badge_html = "" 
            meta_age = "Стаж: <span style='color:red'>Неизвестен</span>"

        inn = legal.get('inn', '-')
        
        items_html += f"""
        <div class="card">
            <div class="img-container">
                {badge_html}
                <img src="{img_url}" onerror="this.src='https://via.placeholder.com/200x300?text=No+Image'" alt="product">
            </div>
            <div class="content">
                <div class="price">{p['price']:.0f} ₽</div>
                <div class="name">{p['name']}</div>
                <div class="brand">Бренд: <span>{p['brand']}</span></div>
                
                <div class="legal-info">
                    <div class="seller-name">{seller_name}</div>
                    <div class="meta">
                        <span>ИНН: {inn}</span>
                        <span>{meta_age}</span>
                    </div>
                </div>

                <div class="links">
                    <a href="{product_url}" target="_blank" class="btn">Карточка товара</a>
                    <a href="{seller_url}" target="_blank" class="btn seller">Профиль продавца</a>
                </div>
            </div>
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>WB Scraper - Новые продавцы ({query})</title>
        <style>
            :root {{ --main-purp: #7212b3; --accent: #2ecc71; --bg: #f8f9fa; --card-bg: #fff; }}
            body {{ font-family: 'Segoe UI', Roboto, sans-serif; background: var(--bg); margin: 0; padding: 40px 20px; color: #333; }}
            .container {{ max-width: 1400px; margin: 0 auto; }}
            h1 {{ text-align: center; color: var(--main-purp); margin-bottom: 10px; font-weight: 800; }}
            .subtitle {{ text-align: center; color: #666; margin-bottom: 40px; font-size: 1.1em; }}
            
            .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 25px; }}
            .card {{ background: var(--card-bg); border-radius: 20px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.05); transition: 0.3s; display: flex; flex-direction: column; border: 1px solid #eee; }}
            .card:hover {{ transform: translateY(-8px); box-shadow: 0 15px 35px rgba(114, 18, 179, 0.12); }}
            
            .img-container {{ position: relative; width: 100%; height: 380px; background: #f0f0f0; }}
            .card img {{ width: 100%; height: 100%; object-fit: cover; }}
            
            .badge {{ position: absolute; top: 15px; left: 15px; padding: 6px 12px; border-radius: 8px; font-size: 0.8em; font-weight: 700; color: #fff; z-index: 10; box-shadow: 0 4px 10px rgba(0,0,0,0.2); }}
            .age-new {{ background: #2ecc71; }}
            .age-young {{ background: #3498db; }}
            
            .content {{ padding: 20px; display: flex; flex-direction: column; flex-grow: 1; }}
            .price {{ font-size: 1.7em; color: var(--main-purp); font-weight: 800; margin-bottom: 5px; }}
            .name {{ font-weight: 600; font-size: 1em; margin-bottom: 10px; height: 2.8em; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; line-height: 1.4; }}
            .brand {{ font-size: 0.9em; color: #888; margin-bottom: 15px; }}
            .brand span {{ color: #333; font-weight: 600; }}
            
            .legal-info {{ background: #fbf8ff; padding: 15px; border-radius: 12px; margin-bottom: 20px; border: 1px dashed #dcb8ff; }}
            .seller-name {{ font-weight: 700; font-size: 0.9em; margin-bottom: 5px; color: #444; }}
            .meta {{ display: flex; justify-content: space-between; font-size: 0.75em; color: #777; }}
            
            .links {{ margin-top: auto; display: flex; flex-direction: column; gap: 8px; }}
            .btn {{ text-align: center; padding: 12px; border-radius: 12px; text-decoration: none; font-size: 0.9em; font-weight: 700; transition: 0.2s; }}
            .btn {{ background: #f0f0f5; color: #333; }}
            .btn.seller {{ background: var(--main-purp); color: #fff; }}
            .btn:hover {{ opacity: 0.9; transform: scale(1.02); }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔍 Результаты для: {query}</h1>
            <p class="subtitle">Фильтр: продавцы со стажем до 2 лет</p>
            <div class="grid">
                {items_html}
            </div>
        </div>
    </body>
    </html>
    """
    filename = f"results_{query.replace(' ', '_')}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    return filename

from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress

# --- Хендлеры ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот для поиска свежих ИП на Wildberries.\n"
        "Выберите действие:",
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("Выберите действие:", reply_markup=get_main_menu())

@dp.callback_query(F.data == "toggle_blacklist")
async def toggle_blacklist(callback: CallbackQuery):
    global USE_BLACKLIST
    USE_BLACKLIST = not USE_BLACKLIST
    await callback.message.edit_reply_markup(reply_markup=get_settings_menu())
    await callback.answer(f"Черный список: {'Включен' if USE_BLACKLIST else 'Выключен'}")

@dp.callback_query(F.data == "clear_blacklist")
async def clear_blacklist(callback: CallbackQuery):
    if os.path.exists(BLACKLIST_FILE):
        os.remove(BLACKLIST_FILE)
    await callback.answer("✅ История просмотров очищена!")

@dp.callback_query(F.data == "categories")
async def cb_categories(callback: CallbackQuery):
    with suppress(TelegramBadRequest):
        await callback.message.edit_text("📂 Выберите категорию:", reply_markup=get_categories_menu())

@dp.callback_query(F.data.startswith("cat_"))
async def cb_open_category(callback: CallbackQuery):
    cat_key = callback.data.split("_", 1)[1]
    cat_data = CATEGORIES.get(cat_key, {})
    cat_name = cat_data.get("name", "Категория")
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(f"📂 Категория: {cat_name}\nЧто ищем?", reply_markup=get_items_menu(cat_key))

@dp.callback_query(F.data == "manual_search")
async def cb_manual_search(callback: CallbackQuery):
    await callback.message.answer("✍️ Введите поисковый запрос:")

@dp.callback_query(F.data == "settings")
async def cb_settings(callback: CallbackQuery):
    proxy_count = 0
    if os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, "r") as f:
            proxy_count = len([l for l in f if l.strip()])
    
    status_text = "используются" if USE_PROXY else "НЕ используются (прямое соединение)"
    text = (
        f"⚙️ **Настройки**\n"
        f"Режим: Прокси {status_text}\n"
        f"Загружено прокси: {proxy_count}\n\n"
        f"Чтобы добавить прокси, отправьте файл `proxies.txt` или сообщение, начинающееся с `proxy:`\n"
        f"Формат: `http://user:pass@ip:port` или `socks5://...`"
    )
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_settings_menu())

@dp.callback_query(F.data == "toggle_proxy")
async def cb_toggle_proxy(callback: CallbackQuery):
    global USE_PROXY
    USE_PROXY = not USE_PROXY
    await cb_settings(callback)

@dp.message(F.text & F.text.startswith("proxy:"))
async def add_proxy_text(message: Message):
    proxies = message.text.replace("proxy:", "").strip().split("\n")
    valid_proxies = [p.strip() for p in proxies if p.strip()]
    
    if valid_proxies:
        with open(PROXY_FILE, "a", encoding="utf-8") as f:
            for p in valid_proxies:
                f.write(f"{p}\n")
        await message.answer(f"✅ Добавлено {len(valid_proxies)} прокси.")
    else:
        await message.answer("❌ Неверный формат.")

@dp.message(F.document)
async def handle_docs(message: Message):
    if message.document.file_name == "proxies.txt":
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        proxies_content = await bot.download_file(file.file_path)
        
        # Перезаписываем файл
        with open(PROXY_FILE, "wb") as f:
            f.write(proxies_content.read())
            
        await message.answer("✅ Файл с прокси обновлен!")

@dp.callback_query(F.data.startswith("search_"))
async def cb_search_item(callback: CallbackQuery):
    query = callback.data.split("_", 1)[1]
    await run_search(callback.message, query, is_callback=True)

@dp.message(F.text)
async def handle_text_search(message: Message):
    if message.text.startswith("proxy:"): return
    await run_search(message, message.text)

async def run_search(message: Message, query_input: str, is_callback: bool = False):
    # Разделяем запрос на несколько, если есть запятые или переносы строк
    queries = [q.strip() for q in query_input.replace("\n", ",").split(",") if q.strip()]
    if not queries: return

    status_text = f"🔍 Начинаю мульти-поиск по {len(queries)} запросам..."
    msg_to_edit = None
    if is_callback:
        with suppress(TelegramBadRequest):
            msg_to_edit = await message.edit_text(status_text, parse_mode="Markdown")
    
    if not msg_to_edit:
        msg_to_edit = await message.answer(status_text, parse_mode="Markdown")
    
    api = WBApi(use_proxy=USE_PROXY)

    try:
        all_raw_products = []
        blacklist = load_blacklist() if USE_BLACKLIST else set()
        
        # 1. СБОР ТОВАРОВ (Асинхронно по всем запросам)
        async def fetch_query_products(q):
            q_products = []
            sort = random.choice(['popular', 'newly', 'priceup', 'pricedown', 'rate'])
            # Сканируем по 5 страниц для каждого запроса (чтобы не перегружать)
            for p_idx in range(1, 6):
                res = await api.search_products(q, limit=100, page=p_idx, sort=sort)
                if not res: break
                q_products.extend(res)
                await asyncio.sleep(0.1)
            return q_products

        await msg_to_edit.edit_text(f"⏳ Собираю выдачу по {len(queries)} запросам параллельно...", parse_mode="Markdown")
        
        # Запускаем сбор для всех запросов одновременно
        tasks = [fetch_query_products(q) for q in queries]
        results_list = await asyncio.gather(*tasks)
        
        for res in results_list:
            all_raw_products.extend(res)

        if not all_raw_products:
            await msg_to_edit.edit_text("😔 Ни по одному запросу ничего не найдено.")
            return

        # Убираем дубликаты товаров и фильтруем по черному списку
        seen_ids = set()
        unique_products = []
        for p in all_raw_products:
            pid = p.get('id')
            sid = str(p.get("supplierId"))
            if pid not in seen_ids and sid not in blacklist:
                unique_products.append(p)
                seen_ids.add(pid)

        # Группируем по продавцам
        sellers_products = {}
        for p in unique_products:
            sid = p.get("supplierId")
            if sid:
                if sid not in sellers_products:
                    sellers_products[sid] = []
                sellers_products[sid].append(p)

        total_scanned = len(unique_products)
        results_data = [] 
        seller_cache = {} 
        new_seen_sellers = set()
        
        await msg_to_edit.edit_text(f"✅ Собрано {total_scanned} товаров.\n🧐 Проверяю {len(sellers_products)} уникальных продавцов...", parse_mode="Markdown")

        # 2. ПРОВЕРКА ПРОДАВЦОВ (Последовательно для безопасности)
        for i, (supp_id, p_list) in enumerate(sellers_products.items(), 1):
            if supp_id not in seller_cache:
                try:
                    age_res = await asyncio.wait_for(api.get_approx_seller_age(supp_id, p_list), timeout=20.0)
                    l_info = await api.get_seller_legal_info(supp_id)
                    seller_cache[supp_id] = {"age_data": age_res, "legal": l_info}
                except Exception as e:
                    logging.error(f"Error fetching info for seller {supp_id}: {e}")
                    seller_cache[supp_id] = {"age_data": {"age": None, "type": "error"}, "legal": {}}
                
                await asyncio.sleep(0.05)

            seller_data = seller_cache[supp_id]
            age_data = seller_data["age_data"]
            age = age_data.get("age") or 100

            if age <= 24:
                p = p_list[0]
                price_raw = p.get("salePriceU") or p.get("priceU") or p.get("sizes", [{}])[0].get("price", {}).get("total")
                price = (price_raw / 100) if price_raw else 0
                
                results_data.append({
                    "id": p.get("id"),
                    "name": p.get("name", "Без названия"),
                    "brand": p.get("brand", "Без бренда"),
                    "price": price,
                    "supplierId": supp_id,
                    "seller_name": p.get('supplier') or age_data.get("name") or "Имя скрыто",
                    "age_months": age,
                    "age_type": age_data.get("type", "unknown"),
                    "legal_info": seller_data["legal"]
                })
                new_seen_sellers.add(supp_id)
            
            if i % 5 == 0 or i == len(sellers_products):
                with suppress(TelegramBadRequest):
                    await msg_to_edit.edit_text(
                        f"⏳ Проверка продавцов: {i}/{len(sellers_products)}\n"
                        f"✅ Подходящих новичков: {len(results_data)}", 
                        parse_mode="Markdown"
                    )

        if not results_data:
            await msg_to_edit.edit_text(f"😕 После фильтрации {len(queries)} запросов ничего нового не найдено.")
            return

        await msg_to_edit.edit_text("⏳ Генерирую общий HTML-отчет...")
        
        # Генерируем в отдельном потоке, чтобы не блокировать бот
        filename = await asyncio.to_thread(
            generate_html_report, 
            ", ".join(queries[:3]) + ("..." if len(queries)>3 else ""), 
            results_data
        )
        
        if USE_BLACKLIST and new_seen_sellers:
            save_to_blacklist(new_seen_sellers)
        
        await msg_to_edit.edit_text("📤 Отправляю файл в Telegram...")

        # Отправляем с большим таймаутом (5 минут для тяжелых файлов)
        try:
            await message.answer_document(
                FSInputFile(filename),
                caption=f"✅ Мульти-поиск завершен!\nЗапросы: {', '.join(queries)}\nНайдено новых продавцов: {len(results_data)}",
                parse_mode="Markdown",
                request_timeout=300 
            )
            with suppress(Exception):
                await msg_to_edit.delete()
        except Exception as send_error:
            logging.error(f"Error sending document: {send_error}")
            await msg_to_edit.edit_text(f"⚠️ Файл создан ({filename}), но не удалось отправить его в Telegram из-за таймаута. Он сохранен на сервере.")
            
    except Exception as e:
        logging.error(f"Error in run_search: {e}")
        error_msg = f"⚠️ Произошла ошибка: {str(e)[:100]}"
        with suppress(Exception):
            await msg_to_edit.edit_text(error_msg)
    finally:
        await api.close()

async def main():
    print("Бот запущен...")
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            await asyncio.sleep(5) # Ждем перед рестартом

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")