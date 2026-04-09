"""
LAB 04: Сравнение подходов
1) FOR UPDATE (решение из lab_02)
2) Idempotency-Key + middleware (lab_04)
"""

import pytest
import asyncio
import uuid
import httpx

BASE_URL = "http://localhost:8082"


async def create_test_order() -> uuid.UUID:
    """Создать тестового пользователя и заказ для теста."""
    async with httpx.AsyncClient() as client:
        user_resp = await client.post(
            f"{BASE_URL}/api/users",
            json={"email": f"test_{uuid.uuid4().hex[:8]}@example.com", "name": "Test User"}
        )
        user_id = user_resp.json()["id"]

        order_resp = await client.post(
            f"{BASE_URL}/api/orders",
            json={"user_id": user_id}
        )
        return uuid.UUID(order_resp.json()["id"])


@pytest.mark.asyncio
async def test_compare_for_update_and_idempotency_behaviour():
    """
    TODO: Реализовать сравнительный тест/сценарий.

    Минимум сравнения:
    1) Повтор запроса с mode='for_update':
       - защита от гонки на уровне БД,
       - повтор может вернуть бизнес-ошибку "already paid".
    2) Повтор запроса с mode='unsafe' + Idempotency-Key:
       - второй вызов возвращает тот же кэшированный успешный ответ,
         без повторного списания.

    В конце добавьте вывод:
    - чем отличаются цели и UX двух подходов,
    - почему они не взаимоисключающие и могут использоваться вместе.
    """

    print("\n" + "="*60)
    print("СРАВНЕНИЕ: FOR UPDATE vs Idempotency-Key")
    print("="*60)

    # ===== ТЕСТ 1: FOR UPDATE =====
    print("\n🔒 ТЕСТ 1: Повторный запрос с mode='for_update'")
    print("-" * 60)

    order_1 = await create_test_order()
    print(f"📝 Заказ создан: {order_1}")

    async with httpx.AsyncClient() as client:
        # Первый запрос (успешен)
        print(f"\n📡 Запрос 1 (for_update):")
        resp1 = await client.post(
            f"{BASE_URL}/api/payments/retry-demo",
            json={"order_id": str(order_1), "mode": "for_update"}
        )
        print(f"   Статус: {resp1.status_code}")
        print(f"   Ответ: {resp1.json()}")

        # Второй запрос (уже оплачено)
        print(f"\n📡 Запрос 2 (for_update) - повтор:")
        resp2 = await client.post(
            f"{BASE_URL}/api/payments/retry-demo",
            json={"order_id": str(order_1), "mode": "for_update"}
        )
        print(f"   Статус: {resp2.status_code}")
        print(f"   Ответ: {resp2.json()}")

        for_update_result = {
            "first_status": resp1.status_code,
            "second_status": resp2.status_code,
            "second_success": resp2.json().get("success", False),
            "second_message": resp2.json().get("message", "")
        }

    # ===== ТЕСТ 2: Idempotency-Key =====
    print("\n\n🔑 ТЕСТ 2: Повторный запрос с Idempotency-Key (mode='unsafe')")
    print("-" * 60)

    order_2 = await create_test_order()
    idempotency_key = f"compare-test-{uuid.uuid4().hex[:8]}"
    print(f"📝 Заказ создан: {order_2}")
    print(f"🔑 Idempotency-Key: {idempotency_key}")

    async with httpx.AsyncClient() as client:
        # Первый запрос (успешен)
        print(f"\n📡 Запрос 1 (с Idempotency-Key):")
        resp3 = await client.post(
            f"{BASE_URL}/api/payments/retry-demo",
            json={"order_id": str(order_2), "mode": "unsafe"},
            headers={"Idempotency-Key": idempotency_key}
        )
        print(f"   Статус: {resp3.status_code}")
        print(f"   Заголовки: {dict(resp3.headers)}")
        print(f"   Ответ: {resp3.json()}")

        # Второй запрос (кэшированный ответ)
        print(f"\n📡 Запрос 2 (тот же Idempotency-Key):")
        resp4 = await client.post(
            f"{BASE_URL}/api/payments/retry-demo",
            json={"order_id": str(order_2), "mode": "unsafe"},
            headers={"Idempotency-Key": idempotency_key}
        )
        print(f"   Статус: {resp4.status_code}")
        print(f"   Заголовки: {dict(resp4.headers)}")
        print(f"   Ответ: {resp4.json()}")

        is_cached = resp4.headers.get("x-idempotency-replayed") == "true"

        idempotency_result = {
            "first_status": resp3.status_code,
            "second_status": resp4.status_code,
            "is_cached": is_cached,
            "second_success": resp4.json().get("success", False)
        }

    # ===== СРАВНЕНИЕ =====
    print("\n\n" + "="*60)
    print("СРАВНИТЕЛЬНЫЙ АНАЛИЗ")
    print("="*60)

    print("\n📊 FOR UPDATE (Lab 02):")
    print(f"   - Первый запрос:  {for_update_result['first_status']} {'✅' if for_update_result['first_status'] == 200 else '❌'}")
    print(f"   - Второй запрос:  {for_update_result['second_status']} {'✅' if for_update_result['second_status'] == 200 else '⚠️ '}")
    print(f"   - Результат:      {for_update_result['second_message']}")
    print(f"   - Тип защиты:     База данных (REPEATABLE READ + блокировка строки)")
    print(f"   - Цель:           Предотвращение race condition при конкурентном доступе")

    print("\n📊 Idempotency-Key (Lab 04):")
    print(f"   - Первый запрос:  {idempotency_result['first_status']} ✅")
    print(f"   - Второй запрос:  {idempotency_result['second_status']} ✅")
    print(f"   - Кэширован:      {'ДА ✅' if idempotency_result['is_cached'] else 'НЕТ ❌'}")
    print(f"   - Тип защиты:     API уровень (ключ идемпотентности)")
    print(f"   - Цель:           Предотвращение повторной обработки того же намерения")

    print("\n🔍 КЛЮЧЕВЫЕ РАЗЛИЧИЯ:")
    print("-" * 60)
    print("1. УРОВЕНЬ ЗАЩИТЫ:")
    print("   • FOR UPDATE:     База данных (транзакционный уровень)")
    print("   • Idempotency:    API / Приложение (уровень HTTP)")
    print()
    print("2. ПОВЕДЕНИЕ ПРИ ПОВТОРЕ:")
    print("   • FOR UPDATE:     Второй запрос получает ошибку 'already paid'")
    print("   • Idempotency:    Второй запрос получает ТОТ ЖЕ успешный ответ")
    print()
    print("3. UX (ПОЛЬЗОВАТЕЛЬСКИЙ ОПЫТ):")
    print("   • FOR UPDATE:     Клиент видит ошибку, не знает успешна ли оплата")
    print("   • Idempotency:    Клиент видит успех (тот же ответ), уверен в результате")
    print()
    print("4. СЦЕНАРИИ ИСПОЛЬЗОВАНИЯ:")
    print("   • FOR UPDATE:     Конкурентные запросы от разных клиентов/источников")
    print("   • Idempotency:    Retry от одного клиента после таймаута/обрыва связи")

    print("\n💡 РЕКОМЕНДАЦИЯ:")
    print("-" * 60)
    print("Эти подходы НЕ взаимоисключающие, а ДОПОЛНЯЮТ друг друга:")
    print()
    print("✅ Используйте Idempotency-Key для:")
    print("   • Защиты от retry после сетевых ошибок")
    print("   • Обеспечения идемпотентности API для клиентов")
    print("   • Сохранения положительного UX (тот же ответ при повторе)")
    print()
    print("✅ Используйте FOR UPDATE для:")
    print("   • Защиты от race condition в высококонкурентных сценариях")
    print("   • Гарантии целостности данных на уровне БД")
    print("   • Блокировки ресурса на время транзакции")
    print()
    print("🎯 Идеальная архитектура: ОБА механизма вместе!")
    print("   Idempotency-Key (API) + FOR UPDATE (БД) = Максимальная надёжность")

    # Проверки
    assert idempotency_result["is_cached"], "Idempotency-Key должен вернуть кэшированный ответ"
    print("\n✅ Тест сравнения завершен успешно!")


if __name__ == "__main__":
    asyncio.run(test_compare_for_update_and_idempotency_behaviour())
