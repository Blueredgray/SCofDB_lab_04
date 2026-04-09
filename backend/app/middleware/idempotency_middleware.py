"""Idempotency middleware implementation for LAB 04."""

import hashlib
import json
from typing import Callable, Optional
from datetime import datetime, timedelta

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware для идемпотентности POST-запросов оплаты.

    Идея:
    - Клиент отправляет `Idempotency-Key` в header.
    - Если запрос с таким ключом уже выполнялся для того же endpoint и payload,
      middleware возвращает кэшированный ответ (без повторного списания).
    """

    def __init__(self, app, ttl_seconds: int = 24 * 60 * 60):
        super().__init__(app)
        self.ttl_seconds = ttl_seconds
        # Пути, для которых применяется идемпотентность
        self.idempotent_paths = ["/api/payments/retry-demo", "/api/payments/pay"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Реализация алгоритма идемпотентности.
        """
        # 1) Пропускаем только целевые запросы: POST на payment endpoints
        if request.method != "POST" or not any(
            request.url.path.endswith(path) for path in self.idempotent_paths
        ):
            return await call_next(request)

        # 2) Читаем Idempotency-Key из headers
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            # Если ключа нет - обычная обработка
            return await call_next(request)

        # 3) Считаем hash тела запроса
        body = await request.body()
        request_hash = self.build_request_hash(body)

        # Восстанавливаем body для downstream (т.к. body уже прочитано)
        async def receive():
            return {"type": "http.request", "body": body}
        request._receive = receive

        # Получаем сессию БД из request.state (установлено в зависимостях)
        db: Optional[AsyncSession] = getattr(request.state, "db", None)

        if not db:
            # Если нет сессии БД, просто пропускаем
            return await call_next(request)

        try:
            # 4) Проверяем существующую запись в БД
            existing = await self._get_idempotency_record(
                db, idempotency_key, request.method, request.url.path
            )

            if existing:
                # Проверяем hash запроса
                existing_hash = existing["request_hash"]

                if existing_hash != request_hash:
                    # Тот же ключ, но другой payload - конфликт
                    return JSONResponse(
                        status_code=409,
                        content={
                            "detail": "Idempotency-Key уже использован с другим payload",
                            "key": idempotency_key
                        }
                    )

                # Тот же ключ и тот же hash - возвращаем кэшированный ответ
                if existing["status"] == "completed" and existing["response_body"]:
                    response_body = existing["response_body"]
                    status_code = existing["status_code"] or 200

                    # Добавляем заголовок для индикации кэшированного ответа
                    response = JSONResponse(
                        content=response_body,
                        status_code=status_code,
                        headers={"X-Idempotency-Replayed": "true"}
                    )
                    return response

                # Если статус processing - ждем (или можно вернуть 409)
                if existing["status"] == "processing":
                    return JSONResponse(
                        status_code=409,
                        content={
                            "detail": "Запрос с таким Idempotency-Key уже обрабатывается",
                            "key": idempotency_key
                        }
                    )

            # 5) Создаем запись со статусом processing
            await self._create_idempotency_record(
                db, idempotency_key, request.method, request.url.path, request_hash
            )
            await db.commit()

            # 6) Выполняем downstream request
            response = await call_next(request)

            # 7) Сохраняем ответ в БД
            await self._cache_response(
                db, idempotency_key, request.method, request.url.path, response
            )
            await db.commit()

            return response

        except Exception as e:
            # При ошибке обновляем статус на failed
            try:
                await self._update_status(
                    db, idempotency_key, request.method, request.url.path, "failed"
                )
                await db.commit()
            except:
                pass
            raise

    async def _get_idempotency_record(
        self, db: AsyncSession, key: str, method: str, path: str
    ) -> Optional[dict]:
        """Получить запись idempotency_key из БД."""
        result = await db.execute(
            text("""
                SELECT idempotency_key, request_hash, status, status_code, response_body, expires_at
                FROM idempotency_keys
                WHERE idempotency_key = :key 
                  AND request_method = :method 
                  AND request_path = :path
                  AND expires_at > NOW()
            """),
            {"key": key, "method": method, "path": path}
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def _create_idempotency_record(
        self, db: AsyncSession, key: str, method: str, path: str, req_hash: str
    ):
        """Создать новую запись idempotency_key."""
        expires_at = datetime.utcnow() + timedelta(seconds=self.ttl_seconds)
        await db.execute(
            text("""
                INSERT INTO idempotency_keys 
                (idempotency_key, request_method, request_path, request_hash, status, expires_at)
                VALUES (:key, :method, :path, :hash, 'processing', :expires)
                ON CONFLICT (idempotency_key, request_method, request_path) 
                DO NOTHING
            """),
            {"key": key, "method": method, "path": path, "hash": req_hash, "expires": expires_at}
        )

    async def _cache_response(
        self, db: AsyncSession, key: str, method: str, path: str, response: Response
    ):
        """Сохранить кэш ответа."""
        # Читаем тело ответа
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        try:
            body_json = json.loads(response_body.decode())
        except:
            body_json = None

        await db.execute(
            text("""
                UPDATE idempotency_keys 
                SET status = 'completed',
                    status_code = :status_code,
                    response_body = :body,
                    updated_at = NOW()
                WHERE idempotency_key = :key 
                  AND request_method = :method 
                  AND request_path = :path
            """),
            {
                "key": key, 
                "method": method, 
                "path": path,
                "status_code": response.status_code,
                "body": json.dumps(body_json) if body_json else None
            }
        )

    async def _update_status(
        self, db: AsyncSession, key: str, method: str, path: str, status: str
    ):
        """Обновить статус записи."""
        await db.execute(
            text("""
                UPDATE idempotency_keys 
                SET status = :status, updated_at = NOW()
                WHERE idempotency_key = :key 
                  AND request_method = :method 
                  AND request_path = :path
            """),
            {"key": key, "method": method, "path": path, "status": status}
        )

    @staticmethod
    def build_request_hash(raw_body: bytes) -> str:
        """Стабильный хэш тела запроса для проверки reuse ключа с другим payload."""
        return hashlib.sha256(raw_body).hexdigest()

    @staticmethod
    def encode_response_payload(body_obj) -> str:
        """Сериализация response body для сохранения в idempotency_keys."""
        return json.dumps(body_obj, ensure_ascii=False)
