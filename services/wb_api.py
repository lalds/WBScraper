import aiohttp
from aiohttp_socks import ProxyConnector
import random
import asyncio
import os
import logging
from datetime import datetime
from aiohttp import ClientTimeout
from fake_useragent import UserAgent

from config import HEADERS, DEFAULT_PARAMS, SELLER_INFO_URL, PRODUCT_DETAIL_URL, SEARCH_URL, DELAY_MIN, DELAY_MAX, PROXY_FILE

class WBApi:
    def __init__(self, use_proxy=True, max_retries=5):
        self.use_proxy = use_proxy
        self.max_retries = max_retries
        self.proxies = self._load_proxies()
        self.ua = UserAgent()
        self.session = None # Initialize session to None
        print(f"[API] Инициализация. Режим прокси: {use_proxy}. Загружено {len(self.proxies)} прокси.")

    async def __aenter__(self):
        await self._get_session() # Ensure session is created when entering context
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close() # Close session when exiting context

    async def _get_session(self):
        if self.session is None or self.session.closed:
            # Создаем сессию с увеличенными таймаутами по умолчанию
            # total: общий таймаут на весь запрос
            # connect: таймаут на установление соединения
            # sock_read: таймаут на чтение данных из сокета
            timeout = ClientTimeout(total=60, connect=10, sock_read=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    def _load_proxies(self):
        """Загружает список прокси из файла."""
        if not os.path.exists(PROXY_FILE):
            return []
        with open(PROXY_FILE, "r", encoding="utf-8") as f:
            proxies = []
            for line in f:
                p = line.strip()
                if p:
                    # Корректная обработка протоколов
                    if "://" not in p:
                        p = f"http://{p}"
                    proxies.append(p)
        return proxies

    def _get_random_proxy(self):
        """Возвращает случайный прокси или None."""
        if not self.proxies:
            return None
        return random.choice(self.proxies)

    async def _request(self, method, url, params=None, headers=None, timeout_sec=15, retries=None, **kwargs):
        """Универсальный метод запроса с ротацией прокси и обработкой ошибок."""
        last_exception = None
        
        # Используем переданные заголовки или стандартные
        current_headers = headers if headers else HEADERS.copy()
        
        max_attempts = retries if retries is not None else self.max_retries
        for attempt in range(max_attempts):
            proxy = self._get_random_proxy() if self.use_proxy else None
            connector = ProxyConnector.from_url(proxy) if proxy else None
            
            # Генерируем новый User-Agent для каждой попытки
            current_headers["User-Agent"] = self.ua.random
            
            print(f"[API] Attempt {attempt+1}/{self.max_retries} | URL: {url} | Proxy: {'Internal' if not proxy else proxy} | UA: {current_headers['User-Agent'][:30]}...")
            
            try:
                # Настраиваем таймаут правильно
                timeout = ClientTimeout(total=timeout_sec)
                # Используем общую сессию
                session = await self._get_session()
                
                # Прокси требует отдельного коннектора в aiohttp, если мы хотим менять его на лету
                # Но мы можем просто передать proxy в request, если сессия это позволяет (зависит от версии)
                # В современных версиях aiohttp проще использовать одну сессию без жесткого коннектора
                # Либо создавать сессию на пачку запросов.
                
                async with session.request(method, url, params=params, timeout=timeout, proxy=proxy, **kwargs) as resp:
                        resp_text = await resp.text()
                        
                        if resp.status == 200:
                            # Пробуем распарсить JSON в любом случае, так как WB иногда шлет text/plain вместо application/json
                            try:
                                data = await resp.json()
                                return resp, data
                            except Exception:
                                # Если через resp.json() не вышло (например, заголовок мешает), пробуем вручную через json.loads
                                try:
                                    import json
                                    data = json.loads(resp_text)
                                    return resp, data
                                except Exception:
                                    print(f"[API] JSON Parse Error. Content-Type: {resp.headers.get('Content-Type')}")
                                    print(f"[BODY FULL (TRUNCATED TO 10000)]: {resp_text[:10000]}")
                                    return resp, None
                        
                        elif resp.status == 429:
                            print(f"[🚩 BAN] Proxy {proxy} got 429. Body: {resp_text[:200]}")
                        else:
                            print(f"[⚠️ ERROR] Status: {resp.status} | Body: {resp_text[:250]}")
                            
                        continue # Ретрай при любой ошибке (не 200)
                        
            except Exception as e:
                last_exception = e
                print(f"[❌ FAIL] Proxy {proxy} | {type(e).__name__}: {e}")
                await asyncio.sleep(0.5)
                
        print(f"[💀 DEAD] Failed {url} after {self.max_retries} retries. Last: {last_exception}")
        return None, None

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def search_products(self, query: str, limit: int = 100, page: int = 1, sort: str = 'popular') -> list:
        """Поиск товаров по ключевому слову с поддержкой страниц и сортировки."""
        params = DEFAULT_PARAMS.copy()
        params['query'] = query
        params['page'] = str(page)
        params['sort'] = sort
        
        resp, data = await self._request("GET", SEARCH_URL, params=params, timeout_sec=10)
        
        if resp and resp.status == 200 and data:
            products = data.get('data', {}).get('products', []) or data.get('products', [])
            return products[:limit]
        
        print(f"[API] Search failed. Status: {resp.status if resp else 'No response'}")
        return []

    async def get_product_details(self, nm_id: int) -> dict:
        """Получение деталей товара (имитация просмотра)."""
        params = {
            "appType": "1",
            "curr": "rub",
            "dest": "-1257786",
            "nm": str(nm_id)
        }
        # Используем v1/detail, но без лишних параметров
        resp, data = await self._request("GET", PRODUCT_DETAIL_URL, params=params, timeout_sec=10)
        return data if data else {}

    async def get_seller_info(self, supplier_id: int) -> dict:
        """Получение общей информации о продавце (включая стаж/age)."""
        url = f"https://catalog.wb.ru/sellers/info?supplierId={supplier_id}"
        headers = HEADERS.copy()
        headers["Referer"] = "https://www.wildberries.ru/"
        
        resp, data = await self._request("GET", url, headers=headers, timeout_sec=5, retries=2)
        return data if data else {}

    async def get_seller_legal_info(self, supplier_id: int) -> dict:
        """Получение юридической информации (ИНН) через Web-API."""
        url = f"https://www.wildberries.ru/webapi/seller/info/legal?supplierId={supplier_id}"
        custom_headers = HEADERS.copy()
        custom_headers.update({
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://www.wildberries.ru/seller/{supplier_id}",
            "Accept": "application/json, text/javascript, */*; q=0.01"
        })
        resp, data = await self._request("GET", url, headers=custom_headers, timeout_sec=5, retries=2)
        return data if data else {}

    async def get_earliest_feedback_date(self, nm_id: int) -> datetime:
        """Получение даты самого старого отзыва для товара (Эвристика возраста)."""
        # Пробуем несколько серверов отзывов
        for i in range(1, 3):
            url = f"https://feedbacks{i}.wb.ru/feedbacks/v1/{nm_id}"
            try:
                resp, data = await self._request("GET", url, timeout_sec=5, retries=1)
                if data and "feedbacks" in data:
                    feedbacks = data["feedbacks"]
                    if feedbacks:
                        dates = [f.get("createdDate") for f in feedbacks if f.get("createdDate")]
                        if dates:
                            parsed_dates = [datetime.fromisoformat(d.replace("Z", "+00:00")) for d in dates]
                            return min(parsed_dates)
            except Exception:
                continue
        return None

    async def get_approx_seller_age(self, supplier_id: int, products_sample: list) -> dict:
        """
        Рассчитывает примерный стаж на основе supplierId, nmId и отзывов.
        Возвращает {'age': months, 'type': 'exact'|'estimated'|'unknown'}
        """
        # 1. Пытаемся получить точный возраст через API
        s_info = await self.get_seller_info(supplier_id)
        if s_info and "age" in s_info:
            return {"age": s_info["age"], "type": "exact"}

        # 2. Если API заблокировано (498/429), используем эвристику
        # Пороги supplierId (на основе динамики роста WB):
        # < 1,000,000 - Продавцы со стажем 3+ года
        # 1,000,000 - 1,800,000 - Продавцы зашедшие в 2022-2023
        # > 1,800,000 - Продавцы зашедшие в 2024-2026 (менее 2 лет)
        
        is_new_by_id = supplier_id > 1800000
        
        if not products_sample:
            # Если товаров нет, судим только по ID
            return {"age": 12 if is_new_by_id else 36, "type": "estimated_sid"}
        
        nm_ids = [p.get("id") for p in products_sample if p.get("id")]
        min_nmid = min(nm_ids) if nm_ids else 0
        
        # Пороги nmId:
        # Артикулы до 180-200 млн создавались более 2 лет назад (до фев 2024)
        is_new_by_nm = min_nmid > 200000000
        
        # 3. Уточняем по самому старому отзыву (самый надежный fallback)
        for nm_id in nm_ids[:3]: # Проверяем чуть больше товаров для надежности
            oldest_date = await self.get_earliest_feedback_date(nm_id)
            if oldest_date:
                diff = datetime.now() - oldest_date.replace(tzinfo=None)
                months = diff.days // 30
                return {"age": months, "type": "estimated_feedback"}

        # 4. Если отзывов нет (новый товар), используем комбинацию ID
        if is_new_by_id and is_new_by_nm:
            return {"age": 6, "type": "estimated_combined"} # Очень вероятно новый
        elif not is_new_by_id or not is_new_by_nm:
            return {"age": 30, "type": "estimated_combined"} # Скорее всего старый
            
        return {"age": 12 if is_new_by_id else 30, "type": "estimated_sid"}

    async def random_sleep(self):
        """Задержка между действиями."""
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        print(f"[Delay] Sleeping {delay:.1f}s...")
        await asyncio.sleep(delay)
