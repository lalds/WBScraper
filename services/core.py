from services.wb_api import WBApi
from services.filters import is_valid_seller

class ProductFilter:
    def __init__(self, api: WBApi):
        self.api = api

    async def filter_sellers(self, query: str, limit: int = 10, offset: int = 0) -> list:
        """
        Основной цикл фильтрации товаров.
        Возвращает список подходящих продавцов.
        """
        results = []
        
        # Получаем список товаров
        products = await self.api.search_products(query, limit)
        if not products:
            return []

        print(f"[Filter] Найдено {len(products)} товаров. Начинаем проверку...")

        for item in products:
            product_id = item.get('id')
            supplier_id = item.get('supplierId')

            if not supplier_id:
                continue

            # Имитируем действия пользователя
            await self.api.random_sleep()

            # 1. Заходим в карточку товара (сигнал WB, что мы смотрим)
            await self.api.get_product_details(product_id)

            # 2. Получаем инфо о продавце
            seller_info = await self.api.get_seller_info(supplier_id)
            if not seller_info:
                print(f"[-] Пропуск {product_id}: нет данных продавца")
                continue

            # 3. Применяем фильтры
            is_valid, message = is_valid_seller(seller_info)
            if is_valid:
                print(f"[+] {message}")
                results.append({
                    "product_id": product_id,
                    "supplier_id": supplier_id,
                    "name": item.get('name'),
                    "brand": item.get('brand'),
                    "seller": seller_info.get('name'),
                    "reg_date": seller_info.get('registrationDate')
                })
            else:
                print(f"[-] {message}")

        return results
