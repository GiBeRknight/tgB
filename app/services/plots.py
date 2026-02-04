from __future__ import annotations

from decimal import Decimal

from app.db.models import Plot

PLACE_IMAGES: dict[str, str] = {
    "Green Hills": "https://placehold.co/600x400?text=Green+Hills",
    "Lake View": "https://placehold.co/600x400?text=Lake+View",
    "Sunny Valley": "https://placehold.co/600x400?text=Sunny+Valley",
}


def get_place_image(place_name: str) -> str | None:
    return PLACE_IMAGES.get(place_name)


def format_price(price: Decimal) -> str:
    return f"{price:,.2f}".replace(",", " ")


def format_plot_details(plot: Plot) -> str:
    status = "Продан" if plot.is_sold else "Свободен"
    return (
        f"Статус: {status}\n"
        f"Стоимость: {format_price(plot.price)}\n"
        f"Площадь: {plot.area_m2} м2"
    )
