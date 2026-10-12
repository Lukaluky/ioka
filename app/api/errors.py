from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.errors import (
    AgentInactive,
    DomainError,
    IdempotencyKeyReused,
    InsufficientFunds,
    InvalidCredentials,
    InvalidOrderStatus,
    InvalidToken,
    IssueInProgress,
    LocationNotFound,
    OfferNotFound,
    OrderExpired,
    OrderNotFound,
    OrderValidationError,
    ProviderError,
    ProviderIssueFailed,
    ProviderTimeout,
    SearchNotFound,
    SearchValidationError,
    TicketNotReady,
)

# HTTP-коды для доменных ошибок живут только здесь: use case-ы бросают DomainError,
# ничего не зная про HTTP.
_STATUS_BY_ERROR: dict[type[DomainError], int] = {
    InvalidCredentials: status.HTTP_401_UNAUTHORIZED,
    InvalidToken: status.HTTP_401_UNAUTHORIZED,
    AgentInactive: status.HTTP_403_FORBIDDEN,
    LocationNotFound: status.HTTP_404_NOT_FOUND,
    OfferNotFound: status.HTTP_404_NOT_FOUND,
    ProviderError: status.HTTP_502_BAD_GATEWAY,
    ProviderTimeout: status.HTTP_504_GATEWAY_TIMEOUT,
    SearchNotFound: status.HTTP_404_NOT_FOUND,
    SearchValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    OrderNotFound: status.HTTP_404_NOT_FOUND,
    OrderValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    IdempotencyKeyReused: status.HTTP_409_CONFLICT,
    InvalidOrderStatus: status.HTTP_409_CONFLICT,
    OrderExpired: status.HTTP_409_CONFLICT,
    IssueInProgress: status.HTTP_409_CONFLICT,
    InsufficientFunds: status.HTTP_402_PAYMENT_REQUIRED,
    ProviderIssueFailed: status.HTTP_502_BAD_GATEWAY,
    TicketNotReady: status.HTTP_409_CONFLICT,
}


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        status_code = _STATUS_BY_ERROR.get(type(exc), status.HTTP_400_BAD_REQUEST)
        return _error_response(status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Собираем сообщение из exc.errors(), а не str(exc): последний включает путь к файлу
        # с обработчиком и утекает во внешний ответ API.
        def _format(error: Any) -> str:
            loc = ".".join(str(part) for part in error["loc"])
            return f"{loc}: {error['msg']}"

        message = "; ".join(_format(error) for error in exc.errors())
        return _error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", message)
