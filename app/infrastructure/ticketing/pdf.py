"""Генерация PDF электронного билета (SPEC §11). Вызывается через asyncio.to_thread.

Подписи на английском: Helvetica (base14) не поддерживает кириллицу — с русским
текстом вместо букв рендерятся нечитаемые прямоугольники-заглушки.
"""

import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.domain.offer import FareFamily, Offer
from app.domain.order import Order


def generate_ticket_pdf(order: Order, offer: Offer, fare: FareFamily | None) -> bytes:
    buffer = io.BytesIO()
    # pageCompression=0: содержимое остаётся читаемым текстом внутри PDF (проще отлаживать
    # и проверять в тестах), а для одностраничного билета сжатие не даёт заметной экономии.
    pdf = canvas.Canvas(buffer, pagesize=A4, pageCompression=0)
    _, height = A4
    y = height - 50

    def write(text: str, size: int = 11, step: int = 16) -> None:
        nonlocal y
        pdf.setFont("Helvetica", size)
        pdf.drawString(50, y, text)
        y -= step

    write(f"E-Ticket #{order.id}", size=14, step=24)
    write(f"Order status: {order.status.value}")
    write(f"Ticket numbers: {', '.join(order.ticket_numbers) or '-'}")
    write("")

    fare_label = f"Fare: {order.fare_family}"
    if fare is not None:
        fare_label += f" ({fare.name})"
    write(fare_label)
    if fare is not None:
        carry_on = "yes" if fare.carry_on else "no"
        write(f"Baggage: {fare.baggage_kg} kg, carry-on: {carry_on}")
    write(f"Price: {order.price.amount} {order.price.currency}")
    write("")

    write("Segments:", size=12)
    for segment in offer.segments:
        write(
            f"{segment.flight_number} {segment.origin} -> {segment.destination}  "
            f"{segment.departure_local:%Y-%m-%d %H:%M} -> {segment.arrival_local:%Y-%m-%d %H:%M}"
        )
    write("")

    write("Passengers:", size=12)
    for passenger in order.passengers:
        write(
            f"{passenger.type.value}: {passenger.last_name} {passenger.first_name}, "
            f"document {passenger.document_number}"
        )

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
