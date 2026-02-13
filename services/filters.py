from datetime import datetime, timedelta

def is_valid_seller(seller_info: dict) -> tuple[bool, str]:
    """
    Проверяет продавца на соответствие критериям.
    Возвращает (Passed: bool, Message: str).
    """
    if not seller_info:
        return False, "Не удалось получить данные продавца"

    seller_name = seller_info.get('name', '').strip()
    reg_date_str = seller_info.get('registrationDate')

    # Проверка 1: ИП
    if not seller_name.upper().startswith("ИП"):
        return False, f"Пропуск: Не ИП ({seller_name})"

    # Проверка 2: Дата регистрации < 1 года
    if not reg_date_str:
        return False, "Пропуск: Нет даты регистрации"

    try:
        # Пример даты: 2023-11-20T10:15:20Z
        reg_date = datetime.strptime(reg_date_str[:10], "%Y-%m-%d")
        one_year_ago = datetime.now() - timedelta(days=365)
        
        if reg_date < one_year_ago:
            return False, f"Пропуск: Старый аккаунт (рег: {reg_date.date()})"
        
        return True, f"✅ Подходит! {seller_name} (рег: {reg_date.date()})"
    except Exception as e:
        return False, f"Ошибка проверки даты: {e}"
