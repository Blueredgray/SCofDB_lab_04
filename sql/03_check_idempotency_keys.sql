timing on

-- ============================================
-- LAB 04: Проверка таблицы idempotency_keys
-- ============================================
--
-- Таблица появляется после применения миграции 002_idempotency_keys.sql

SELECT
    idempotency_key,
    request_method,
    request_path,
    status,
    status_code,
    created_at,
    updated_at,
    expires_at
FROM idempotency_keys
ORDER BY created_at DESC
LIMIT 50;
