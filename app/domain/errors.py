class DomainError(Exception):
    """Базовый класс ошибок бизнес-логики. HTTP-код выставляется только в app/api/errors.py."""

    code: str = "domain_error"
    message: str = "Внутренняя ошибка бизнес-логики"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message


class InvalidCredentials(DomainError):
    code = "invalid_credentials"
    message = "Неверный логин или пароль"


class AgentInactive(DomainError):
    code = "agent_inactive"
    message = "Агент деактивирован"


class InvalidToken(DomainError):
    code = "not_authenticated"
    message = "Токен недействителен или истёк"


class LocationNotFound(DomainError):
    code = "location_not_found"
    message = "Локация не найдена"


class OfferNotFound(DomainError):
    code = "offer_not_found"
    message = "Оффер не найден или истёк"


class ProviderError(DomainError):
    code = "provider_error"
    message = "Ошибка внешней системы бронирования"


class ProviderTimeout(DomainError):
    code = "provider_timeout"
    message = "Внешняя система бронирования не ответила вовремя"


class SearchNotFound(DomainError):
    code = "search_not_found"
    message = "Поиск не найден или истёк"


class SearchValidationError(DomainError):
    code = "validation_error"
    message = "Некорректные параметры поиска"


class InvalidOrderStatus(DomainError):
    code = "invalid_order_status"
    message = "Недопустимый переход статуса заказа"


class OrderNotFound(DomainError):
    code = "order_not_found"
    message = "Заказ не найден"


class IdempotencyKeyReused(DomainError):
    code = "idempotency_key_reused"
    message = "Idempotency-Key уже использован с другим телом запроса"


class OrderValidationError(DomainError):
    code = "validation_error"
    message = "Некорректные данные заказа"


class OrderExpired(DomainError):
    code = "order_expired"
    message = "Заказ истёк"


class IssueInProgress(DomainError):
    code = "issue_in_progress"
    message = "Выписка уже выполняется"


class InsufficientFunds(DomainError):
    code = "insufficient_funds"
    message = "Недостаточно средств на балансе"


class ProviderIssueFailed(DomainError):
    code = "provider_issue_failed"
    message = "Провайдер не смог выпустить билет"


class TicketNotReady(DomainError):
    code = "ticket_not_ready"
    message = "Билет ещё не готов"
