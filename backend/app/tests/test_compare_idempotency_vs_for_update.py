"""
LAB 04: Сравнение подходов
1) FOR UPDATE (решение из lab_02)
2) Idempotency-Key + middleware (lab_04)
"""

import pytest
import uuid
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.application.payment_service import PaymentService

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/marketplace"


@pytest.fixture(scope="module")
async def test_engine():
    """Создать движок для тестов."""
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    """Создать сессию БД."""
    async with AsyncSession(test_engine) as session:
        yield session


async def _create_test_order(test_engine) -> tuple:
    """Создать тестовый заказ и вернуть (order_id, user_id)."""
    user_id = uuid.uuid4()
    order_id = uuid.uuid4()

    async with AsyncSession(test_engine) as setup_session:
        async with setup_session.begin():
            await setup_session.execute(
                text("""
                    INSERT INTO users (id, email, name, created_at)
                    VALUES (:user_id, :email, :name, NOW())
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "user_id": user_id,
                    "email": f"test_compare_{order_id}@example.com",
                    "name": "Test User Compare"
                }
            )
            await setup_session.execute(
                text("""
                    INSERT INTO orders (id, user_id, status, total_amount, created_at)
                    VALUES (:order_id, :user_id, 'created', 100.00, NOW())
                """),
                {"order_id": order_id, "user_id": user_id}
            )
            await setup_session.execute(
                text("""
                    INSERT INTO order_status_history (id, order_id, status, changed_at)
                    VALUES (gen_random_uuid(), :order_id, 'created', NOW())
                """),
                {"order_id": order_id}
            )

    return order_id, user_id


async def _cleanup(test_engine, order_id, user_id):
    """Очистить тестовые данные."""
    async with AsyncSession(test_engine) as cleanup_session:
        async with cleanup_session.begin():
            await cleanup_session.execute(
                text("DELETE FROM idempotency_keys WHERE request_path LIKE '%payments%'")
            )
            await cleanup_session.execute(
                text("DELETE FROM order_status_history WHERE order_id = :order_id"),
                {"order_id": order_id}
            )
            await cleanup_session.execute(
                text("DELETE FROM orders WHERE id = :order_id"),
                {"order_id": order_id}
            )
            await cleanup_session.execute(
                text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id}
            )


@pytest.mark.asyncio
async def test_compare_for_update_and_idempotency_behaviour(db_session, test_engine):
    """
    LAB 04: Сравнение двух подходов к защите от повторной оплаты.

    Подход 1: FOR UPDATE (lab_02)
    - Защита от race condition на уровне БД.
    - При повторном запросе (race) вторая транзакция получает ошибку
      "Order already paid" от триггера или FOR UPDATE.
    - Цель: предотвратить параллельную обработку одного заказа.

    Подход 2: Idempotency-Key + middleware (lab_04)
    - Защита от повторов на уровне API-контракта.
    - При повторе с тем же ключом и payload клиент получает
      тот же успешный ответ (из кэша), без повторного списания.
    - Цель: гарантировать, что повторный запрос клиента
      (после обрыва сети) не приведёт к повторной операции.

    Вывод: подходы НЕ взаимоисключающие и дополняют друг друга.
    FOR UPDATE защищает от конкурентных транзакций,
    Idempotency-Key — от повторных запросов клиента.
    """

    # ========================================
    # Подход 1: FOR UPDATE (две параллельные попытки)
    # ========================================
    order_id_1, user_id_1 = await _create_test_order(test_engine)

    try:
        async def attempt_for_update():
            async with AsyncSession(test_engine) as session:
                service = PaymentService(session)
                try:
                    return await service.pay_order_safe(order_id_1)
                except Exception as e:
                    return {"error": str(e), "type": type(e).__name__}

        results_for_update = await asyncio.gather(
            attempt_for_update(),
            attempt_for_update(),
            return_exceptions=True
        )
        await asyncio.sleep(0.3)

        async with AsyncSession(test_engine) as check_session:
            service = PaymentService(check_session)
            history_for_update = await service.get_payment_history(order_id_1)

        # FOR UPDATE: только одна оплата, вторая с ошибкой
        success_fu = sum(1 for r in results_for_update
                         if isinstance(r, dict) and "error" not in r)
        error_fu = sum(1 for r in results_for_update
                       if isinstance(r, dict) and "error" in r)
    finally:
        await _cleanup(test_engine, order_id_1, user_id_1)

    # ========================================
    # Подход 2: Idempotency-Key (повторный запрос через API)
    # ========================================
    order_id_2, user_id_2 = await _create_test_order(test_engine)
    idempotency_key = "compare-test-key-789"
    payload = {"order_id": str(order_id_2), "mode": "for_update"}

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            # Первый запрос с Idempotency-Key
            response1 = await client.post(
                "/api/payments/retry-demo",
                json=payload,
                headers={"Idempotency-Key": idempotency_key}
            )

            # Повторный запрос с тем же ключом
            response2 = await client.post(
                "/api/payments/retry-demo",
                json=payload,
                headers={"Idempotency-Key": idempotency_key}
            )

        body1 = response1.json()
        body2 = response2.json()

        async with AsyncSession(test_engine) as check_session:
            service = PaymentService(check_session)
            history_idem = await service.get_payment_history(order_id_2)

        # Idempotency-Key: оба ответа успешны, но оплата только одна
        is_cached = response2.headers.get("X-Idempotency") == "cached"
    finally:
        await _cleanup(test_engine, order_id_2, user_id_2)

    # ========================================
    # Ассерты и выводы
    # ========================================

    # FOR UPDATE: только одна успешная оплата
    assert success_fu == 1, (
        f"FOR UPDATE: ожидалась 1 успешная оплата, получено {success_fu}"
    )
    assert len(history_for_update) == 1, (
        f"FOR UPDATE: ожидалась 1 запись paid, получено {len(history_for_update)}"
    )

    # Idempotency-Key: только одна оплата, второй ответ из кэша
    assert len(history_idem) == 1, (
        f"Idempotency-Key: ожидалась 1 запись paid, получено {len(history_idem)}"
    )
    assert is_cached, "Второй ответ должен быть из кэша (X-Idempotency: cached)"
    assert body1 == body2, "Ответы должны совпадать"

    print(f"\n{'='*60}")
    print(f"LAB 04: СРАВНЕНИЕ FOR UPDATE vs IDEMPOTENCY-KEY")
    print(f"{'='*60}")
    print(f"\n--- Подход 1: FOR UPDATE (lab_02) ---")
    print(f"  Успешных оплат: {success_fu}")
    print(f"  Ошибок: {error_fu}")
    print(f"  Записей paid в истории: {len(history_for_update)}")
    print(f"  Цель: защита от race condition на уровне БД")
    print(f"  UX: второй конкурентный запрос получает ошибку")
    print(f"  Механизм: SELECT ... FOR UPDATE + триггер БД")
    print(f"\n--- Подход 2: Idempotency-Key + middleware (lab_04) ---")
    print(f"  Успешных ответов: 2 (оба 200 OK)")
    print(f"  Записей paid в истории: {len(history_idem)}")
    print(f"  Второй ответ из кэша: {'Да' if is_cached else 'Нет'}")
    print(f"  Цель: защита от повторных запросов на уровне API")
    print(f"  UX: клиент получает тот же ответ, ничего не сломалось")
    print(f"  Механизм: таблица idempotency_keys + middleware")
    print(f"\n--- Вывод ---")
    print(f"  1. FOR UPDATE защищает от КОНКУРЕНТНЫХ транзакций.")
    print(f"     Вторая параллельная транзакция получает ОШИБКУ.")
    print(f"  2. Idempotency-Key защищает от ПОВТОРНЫХ запросов клиента.")
    print(f"     Клиент получает тот же УСПЕШНЫЙ ответ из кэша.")
    print(f"  3. Подходы НЕ взаимоисключающие — их нужно использовать ВМЕСТЕ.")
    print(f"     FOR UPDATE — от гонок на уровне БД.")
    print(f"     Idempotency-Key — от сетевых повторов на уровне API.")
    print(f"{'='*60}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
