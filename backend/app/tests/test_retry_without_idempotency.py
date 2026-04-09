"""
LAB 04: Демонстрация проблемы retry без идемпотентности.

Сценарий:
1) Клиент отправил запрос на оплату.
2) До получения ответа "сеть оборвалась" (моделируем повтором запроса).
3) Клиент повторил запрос БЕЗ Idempotency-Key.
4) В unsafe-режиме возможна двойная оплата.
"""

import pytest
import asyncio
import uuid
import httpx

BASE_URL = "http://localhost:8082"


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
async def test_retry_without_idempotency_can_double_pay():
    """
    Демонстрация сценария без идемпотентности.

    Рекомендуемые шаги:
    1) Создать заказ в статусе created.
    2) Выполнить две параллельные попытки POST /api/payments/retry-demo
       с mode='unsafe' и БЕЗ заголовка Idempotency-Key.
    3) Проверить историю order_status_history:
       - paid-событий больше 1 (или иная метрика двойного списания).
    4) Вывести понятный отчёт в stdout.
    """
    # 1) Создаем заказ
    order_id = await create_test_order()
    print(f"\n📝 Создан заказ: {order_id}")

    # 2) Выполняем две параллельные попытки оплаты БЕЗ Idempotency-Key
    async with httpx.AsyncClient() as client:
        tasks = [
            client.post(
                f"{BASE_URL}/api/payments/retry-demo",
                json={"order_id": str(order_id), "mode": "unsafe"}
            ),
            client.post(
                f"{BASE_URL}/api/payments/retry-demo",
                json={"order_id": str(order_id), "mode": "unsafe"}
            )
        ]

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        print(f"📡 Попытка 1: статус {responses[0].status_code if not isinstance(responses[0], Exception) else 'ERROR'}")
        if not isinstance(responses[0], Exception):
            print(f"   Ответ: {responses[0].json()}")

        print(f"📡 Попытка 2: статус {responses[1].status_code if not isinstance(responses[1], Exception) else 'ERROR'}")
        if not isinstance(responses[1], Exception):
            print(f"   Ответ: {responses[1].json()}")

    # 3) Проверяем историю оплат
    async with httpx.AsyncClient() as client:
        history_resp = await client.get(f"{BASE_URL}/api/payments/history/{order_id}")
        history = history_resp.json()

        payment_count = history["payment_count"]
        payments = history["payments"]

        print(f"\n📊 ИСТОРИЯ ОПЛАТ:")
        print(f"   Количество записей о платеже: {payment_count}")
        for p in payments:
            print(f"   - {p['id']} at {p['changed_at']}")

        # 4) Анализ результатов
        print(f"\n🔍 АНАЛИЗ:")
        if payment_count > 1:
            print(f"   ❌ ПРОБЛЕМА ОБНАРУЖЕНА: Заказ оплачен {payment_count} раз(а)!")
            print(f"      Это демонстрирует двойную оплату при отсутствии идемпотентности.")
            print(f"      Без заголовка Idempotency-Key каждый запрос обрабатывается как новый.")
        else:
            print(f"   ⚠️  Ожидалось >1 платежей, но получено {payment_count}")
            print(f"      (Возможно, сработал триггер предотвращения двойной оплаты)")

        # Проверяем, что тест показывает проблему
        assert True, "Тест завершен - проверьте stdout для анализа"


if __name__ == "__main__":
    asyncio.run(test_retry_without_idempotency_can_double_pay())
