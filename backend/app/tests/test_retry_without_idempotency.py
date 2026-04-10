"""
LAB 04: Демонстрация проблемы retry без идемпотентности.

Тест показывает, что без Idempotency-Key повторный запрос на оплату
в режиме 'unsafe' может привести к двойному списанию.
"""

import asyncio
import pytest
import uuid
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


@pytest.fixture
async def test_order(test_engine):
    """Создать тестовый заказ со статусом 'created'."""
    user_id = uuid.uuid4()
    order_id = uuid.uuid4()

    async with AsyncSession(test_engine) as setup_session:
        async with setup_session.begin():
            # Создаём пользователя
            await setup_session.execute(
                text("""
                    INSERT INTO users (id, email, name, created_at)
                    VALUES (:user_id, :email, :name, NOW())
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "user_id": user_id,
                    "email": f"test_no_idem_{order_id}@example.com",
                    "name": "Test User No Idempotency"
                }
            )

            # Создаём заказ
            await setup_session.execute(
                text("""
                    INSERT INTO orders (id, user_id, status, total_amount, created_at)
                    VALUES (:order_id, :user_id, 'created', 100.00, NOW())
                """),
                {"order_id": order_id, "user_id": user_id}
            )

            # Записываем начальный статус
            await setup_session.execute(
                text("""
                    INSERT INTO order_status_history (id, order_id, status, changed_at)
                    VALUES (gen_random_uuid(), :order_id, 'created', NOW())
                """),
                {"order_id": order_id}
            )

    yield order_id

    # Очистка после теста
    async with AsyncSession(test_engine) as cleanup_session:
        async with cleanup_session.begin():
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
async def test_retry_without_idempotency_can_double_pay(db_session, test_order, test_engine):
    """
    LAB 04: Демонстрация проблемы — без Idempotency-Key
    повторный запрос в режиме unsafe приводит к двойной оплате.

    Сценарий:
    1) Создан заказ в статусе 'created'.
    2) Два параллельных POST /api/payments/retry-demo (mode='unsafe')
       БЕЗ заголовка Idempotency-Key.
    3) Оба запроса проходят проверку статуса одновременно (race condition).
    4) Ожидаем: в истории заказа 2 записи 'paid'.
    """
    order_id = test_order

    async def payment_attempt(session_factory):
        """Выполнение небезопасной оплаты через PaymentService напрямую."""
        async with AsyncSession(session_factory) as session:
            service = PaymentService(session)
            try:
                return await service.pay_order_unsafe(order_id)
            except Exception as e:
                return {"error": str(e)}

    # Запускаем две попытки параллельно
    results = await asyncio.gather(
        payment_attempt(test_engine),
        payment_attempt(test_engine),
        return_exceptions=True
    )

    # Даём время на завершение транзакций
    await asyncio.sleep(0.3)

    # Проверяем историю оплат
    async with AsyncSession(test_engine) as check_session:
        service = PaymentService(check_session)
        history = await service.get_payment_history(order_id)

    # Без защиты: ожидаем двойную оплату (race condition)
    assert len(history) >= 2, (
        f"Ожидалась двойная оплата (>=2 записи paid), "
        f"но получено {len(history)}. Race condition не обнаружен."
    )

    print(f"\n[LAB 04] Результат БЕЗ идемпотентности:")
    print(f"  Order ID: {order_id}")
    print(f"  Количество paid-событий: {len(history)}")
    print(f"  Результаты попыток:")
    for i, r in enumerate(results, 1):
        if isinstance(r, Exception):
            print(f"    Попытка {i}: ОШИБКА - {type(r).__name__}: {r}")
        else:
            print(f"    Попытка {i}: {r}")
    print(f"  ВЫВОД: Двойная оплата подтверждена!")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
