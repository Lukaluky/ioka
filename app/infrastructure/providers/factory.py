from app.config import get_settings
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.providers.auditing_air_provider import AuditingAirProvider
from app.infrastructure.providers.mock_air_provider import MockAirProvider, MockProviderConfig


def build_air_provider() -> AuditingAirProvider:
    settings = get_settings()
    mock = MockAirProvider(
        MockProviderConfig(
            delay_min_seconds=settings.provider_delay_min_seconds,
            delay_max_seconds=settings.provider_delay_max_seconds,
            timeout_seconds=settings.provider_timeout_seconds,
            failure_rate=settings.provider_failure_rate,
            timeout_rate=settings.provider_timeout_rate,
        )
    )
    return AuditingAirProvider(
        mock,
        get_session_factory(),
        timeout_seconds=settings.provider_timeout_seconds,
        provider_name="mock",
    )
