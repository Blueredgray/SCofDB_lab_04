-- ============================================
-- LAB 04: Идемпотентность платежных запросов
-- ============================================

-- Таблица для хранения ключей идемпотентности
CREATE TABLE IF NOT EXISTS idempotency_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    idempotency_key VARCHAR(255) NOT NULL,
    request_method VARCHAR(16) NOT NULL,
    request_path TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'processing',
    status_code INTEGER,
    response_body JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT idempotency_status_check CHECK (status IN ('processing', 'completed', 'failed'))
);

-- Уникальный constraint: один ключ может использоваться только для одного endpoint с одним методом
ALTER TABLE idempotency_keys 
ADD CONSTRAINT uq_idempotency_key_endpoint 
UNIQUE (idempotency_key, request_method, request_path);

-- Индексы для быстрого lookup
CREATE INDEX IF NOT EXISTS idx_idempotency_keys_lookup 
ON idempotency_keys(idempotency_key, request_method, request_path);

-- Индекс для очистки просроченных ключей
CREATE INDEX IF NOT EXISTS idx_idempotency_keys_expires 
ON idempotency_keys(expires_at) 
WHERE expires_at < NOW();

-- Индекс для поиска по статусу (для cleanup и мониторинга)
CREATE INDEX IF NOT EXISTS idx_idempotency_keys_status 
ON idempotency_keys(status, created_at);

-- Триггер для автоматического обновления updated_at
CREATE OR REPLACE FUNCTION update_idempotency_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_idempotency_timestamp ON idempotency_keys;
CREATE TRIGGER trg_update_idempotency_timestamp
BEFORE UPDATE ON idempotency_keys
FOR EACH ROW
EXECUTE FUNCTION update_idempotency_updated_at();
