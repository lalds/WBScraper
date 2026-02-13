import os

# Токен Telegram бота (замените на свой или используйте .env файл)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8321100059:AAE_s97H-unZ8Y5Ns03Cyjp5946NvZUMNtk")

# Настройки парсера
SEARCH_URL = "https://search.wb.ru/exactmatch/ru/common/v18/search"
SELLER_INFO_URL = "https://catalog.wb.ru/sellers/info"
PRODUCT_DETAIL_URL = "https://card.wb.ru/cards/v1/detail"

# Заголовки для имитации браузера
HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Origin": "https://www.wildberries.ru",
    "Referer": "https://www.wildberries.ru/",
}

# Параметры поиска
DEFAULT_PARAMS = {
    "appType": "1",
    "curr": "rub",
    "dest": "-1257786",
    "lang": "ru",
    "page": "1",
    "spp": "30",
    "sort": "popular",
    "resultset": "catalog",
}

# Настройки задержки (в секундах)
DELAY_MIN = 20
DELAY_MAX = 30

# Файл с прокси (одна строка - один прокси: http://user:pass@ip:port)
PROXY_FILE = "proxies.txt"
