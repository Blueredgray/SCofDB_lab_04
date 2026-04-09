"""
LAB 04: Проверка идемпотентного повтора запроса.

Цель:
При повторном запросе с тем же Idempotency-Key вернуть
кэшированный результат без повторного списания.
"""

import pytest
import asyncio
import uuid
import httpx

BASE_URL = "http://localhost:8082"
IDEMPOTENCY_KEY = "test-key-12345"


async def create_test_order() -> uuid.UUID:
    """Создать тестового пользователя и заказ для теста."""
    async with httpx.AsyncClient() as client:
        # Создаем пользователя
        user_resp = await client.post(
            f"{BASE_URL}/api/users",
            json={"email": f"test_{uuid.uuid4().hex[:8]}@example.com", "name": "Test User"}
        )
        user_id = user_resp.json()["id"]

        # Создаем заказ
        order_resp = await client.post(
            f"{BASE_URL}/api/orders",
            json={"user_id": user_id}
        )
        return uuid.UUID(order_resp.json()["id"])


@pytest.mark.asyncio
async def test_retry_with_same_key_returns_cached_response():
    """
    TODO: Реализовать тест.

    Рекомендуемые шаги:
    1) Создать заказ в статусе created.
    2) Сделать первый POST /api/payments/retry-demo (mode='unsafe')
       с заголовком Idempotency-Key: fixed-key-123.
    3) Повторить тот же POST с тем же ключом и тем же payload.
    4) Проверить:
       - второй ответ пришёл из кэша (через признак, который вы добавите,
         например header X-Idempotency-Replayed=true),
       - в order_status_history только одно событие paid,
       - в idempotency_keys есть запись completed с response_body/status_code.
    """
    # 1) Создаем заказ
    order_id = await create_test_order()
    print(f"\n📝 Создан заказ: {order_id}")

    test_key = f"test-key-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient() as client:
        # 2) Первый запрос с Idempotency-Key
        print(f"\n📡 ПЕРВЫЙ ЗАПРОС (Idempotency-Key: {test_key})")
        resp1 = await client.post(
            f"{BASE_URL}/api/payments/retry-demo",
            json={"order_id": str(order_id), "mode": "unsafe"},
            headers={"Idempotency-Key": test_key}
        )

        print(f"   Статус: {resp1.status_code}")
        print(f"   Заголовки: {dict(resp1.headers)}")
        body1 = resp1.json()
        print(f"   Тело: {body1}")

        # Сохраняем время первого ответа для сравнения
        first_response_time = body1.get("timestamp", "N/A")

        # 3) Второй запрос с тем же ключом
        print(f"\n📡 ВТОРОЙ ЗАПРОС (тот же Idempotency-Key: {test_key})")
        resp2 = await client.post(
            f"{BASE_URL}/api/payments/retry-demo",
            json={"order_id": str(order_id), "mode": "unsafe"},
            headers={"Idempotency-Key": test_key}
        )

        print(f"   Статус: {resp2.status_code}")
        print(f"   Заголовки: {dict(resp2.headers)}")
        body2 = resp2.json()
        print(f"   Тело: {body2}")

        # 4) Проверяем результаты
        print(f"\n🔍 ПРОВЕРКИ:")

        # Проверяем заголовок X-Idempotency-Replayed
        is_cached = resp2.headers.get("x-idempotency-replayed") == "true"
        print(f"   {'✅' if is_cached else '❌'} Заголовок X-Idempotency-Replayed: {is_cached}")

        # Проверяем историю оплат
        history_resp = await client.get(f"{BASE_URL}/api/payments/history/{order_id}")
        history = history_resp.json()
        payment_count = history["payment_count"]

        print(f"   {'✅' if payment_count == 1 else '❌'} Количество платежей в истории: {payment_count}")

        if payment_count == 1:
            print(f"      ✅ Идемпотентность работает: повторный запрос не создал новый платеж!")
        else:
            print(f"      ❌ Ошибка: ожидался 1 платеж, получено {payment_count}")

        # Выводим сводку
        print(f"\n📊 СВОДКА:")
        print(f"   - Первый запрос: обработан успешно")
        print(f"   - Второй запрос: {'возвращен кэш' if is_cached else 'ОБРАБОТАН ЗАНОВО (ошибка!)'}")
        print(f"   - Двойной платеж: {'отсутствует' if payment_count == 1 else 'ОБНАРУЖЕН'}")

        assert is_cached, "Второй запрос должен вернуть кэшированный ответ (X-Idempotency-Replayed: true)"
        assert payment_count == 1, f"Должен быть только 1 платеж, но найдено {payment_count}"


@pytest.mark.asyncio
async def test_same_key_different_payload_returns_conflict():
    """
    TODO: Реализовать негативный тест.

    Один и тот же Idempotency-Key нельзя использовать с другим payload.
    Ожидается 409 Conflict (или эквивалентная бизнес-ошибка).
    """
    # Создаем два разных заказа
    order_id_1 = await create_test_order()
    order_id_2 = await create_test_order()

    test_key = f"conflict-key-{uuid.uuid4().hex[:8]}"

    print(f"\n📝 Созданы заказы: {order_id_1} и {order_id_2}")
    print(f"🔑 Используем ключ: {test_key}")

    async with httpx.AsyncClient() as client:
        # Первый запрос с заказом 1
        print(f"\n📡 ПЕРВЫЙ ЗАПРОС (order_id: {order_id_1})")
        resp1 = await client.post(
            f"{BASE_URL}/api/payments/retry-demo",
            json={"order_id": str(order_id_1), "mode": "unsafe"},
            headers={"Idempotency-Key": test_key}
        )
        print(f"   Статус: {resp1.status_code}")
        assert resp1.status_code == 200, "Первый запрос должен быть успешным"

        # Второй запрос с тем же ключом, но другим заказом (другой payload)
        print(f"\n📡 ВТОРОЙ ЗАПРОС (тот же ключ, order_id: {order_id_2})")
        resp2 = await client.post(
            f"{BASE_URL}/api/payments/retry-demo",
            json={"order_id": str(order_id_2), "mode": "unsafe"},
            headers={"Idempotency-Key": test_key}
        )
        print(f"   Статус: {resp2.status_code}")
        print(f"   Тело: {resp2.json()}")

        # Проверяем конфликт
        print(f"\n🔍 ПРОВЕРКА:")
        is_conflict = resp2.status_code == 409
        print(f"   {'✅' if is_conflict else '❌'} Код ответа: {resp2.status_code} (ожидался 409)")

        if is_conflict:
            print(f"   ✅ Конфликт обнаружен: ключ нельзя использовать с другим payload!")
        else:
            print(f"   ❌ Ошибка: ожидался 409 Conflict")

        assert is_conflict, "При reuse ключа с другим payload должен возвращаться 409 Conflict"


if __name__ == "__main__":
    asyncio.run(test_retry_with_same_key_returns_cached_response())
    print("\n" + "="*50 + "\n")
    asyncio.run(test_same_key_different_payload_returns_conflict())
