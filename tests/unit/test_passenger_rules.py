from datetime import date

import pytest

from app.domain.order import PassengerType, calculate_age, is_latin_name, passenger_type_matches_age


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("IVAN", True),
        ("Ivanov", True),
        ("O'Brien", True),
        ("Anna-Maria", True),
        ("Иван", False),
        ("Ivan123", False),
        ("", False),
    ],
)
def test_is_latin_name(value: str, expected: bool) -> None:
    assert is_latin_name(value) is expected


def test_calculate_age_before_birthday() -> None:
    assert calculate_age(date(2000, 6, 15), date(2026, 6, 14)) == 25


def test_calculate_age_on_birthday() -> None:
    assert calculate_age(date(2000, 6, 15), date(2026, 6, 15)) == 26


@pytest.mark.parametrize(
    ("passenger_type", "birth_date", "on_date", "expected"),
    [
        (PassengerType.ADT, date(2014, 1, 1), date(2026, 1, 1), True),  # ровно 12
        (PassengerType.ADT, date(2014, 1, 2), date(2026, 1, 1), False),  # на день младше 12
        (PassengerType.CHD, date(2024, 1, 1), date(2026, 1, 1), True),  # ровно 2
        (PassengerType.CHD, date(2024, 1, 2), date(2026, 1, 1), False),  # младше 2 -> не CHD
        (PassengerType.CHD, date(2014, 1, 1), date(2026, 1, 1), False),  # ровно 12 -> не CHD
        (PassengerType.INF, date(2025, 1, 1), date(2026, 1, 1), True),  # 1 год
        (PassengerType.INF, date(2024, 1, 1), date(2026, 1, 1), False),  # ровно 2 -> не INF
    ],
)
def test_passenger_type_matches_age(
    passenger_type: PassengerType, birth_date: date, on_date: date, expected: bool
) -> None:
    assert passenger_type_matches_age(passenger_type, birth_date, on_date) is expected
