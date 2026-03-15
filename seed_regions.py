"""
Seed script: populate DB with regions from the website.
Run once: python seed_regions.py
"""
import asyncio

from bot.db import init_db, async_session
from bot.models import Region


REGIONS = [
    # ── Сухий Лиман (3 типи) ──
    {
        "name": "Сухий Лиман",
        "price": 3200,
        "plots_number": 3,
        "size": 5,
        "describe": (
            "З комунікаціями (світло, вода, дорога).\n"
            "Приватне поселення поруч із містом, де поєднуються тиша, безпека "
            "та готова інфраструктура.\n"
            "Ділянки з видом на лиман — для тих, хто цінує простір, безпеку та комфорт."
        ),
        "link_map": "https://www.google.com/maps?q=46.3975,30.6285",
        "link_youtube": "https://www.youtube.com/watch?v=CHMnz-35nlU",
    },
    {
        "name": "Сухий Лиман",
        "price": 2500,
        "plots_number": 3,
        "size": 5,
        "describe": (
            "Видові ділянки, без комунікацій.\n"
            "Приватне поселення поруч із містом, де поєднуються тиша, безпека "
            "та готова інфраструктура.\n"
            "Ділянки з видом на лиман — для тих, хто цінує простір, безпеку та комфорт."
        ),
        "link_map": "https://www.google.com/maps?q=46.3975,30.6285",
        "link_youtube": "https://www.youtube.com/watch?v=CHMnz-35nlU",
    },
    {
        "name": "Сухий Лиман",
        "price": 1700,
        "plots_number": 3,
        "size": 5,
        "describe": (
            "Ділянки з видом на лиман, без комунікацій.\n"
            "Приватне поселення поруч із містом, де поєднуються тиша, безпека "
            "та готова інфраструктура.\n"
            "Ділянки з видом на лиман — для тих, хто цінує простір, безпеку та комфорт."
        ),
        "link_map": "https://www.google.com/maps?q=46.3975,30.6285",
        "link_youtube": "https://www.youtube.com/watch?v=CHMnz-35nlU",
    },
    # ── Вапнярка 2 ──
    {
        "name": "Вапнярка 2",
        "price": 1200,
        "plots_number": 31,
        "size": 6,
        "describe": (
            "Ділянки від 6 до 9 соток із краєвидом на лиман. "
            "Зручний асфальтований під'їзд забезпечує комфортний доїзд у будь-яку пору року. "
            "До масиву вже підведено воду та електропостачання.\n"
            "Ідеальне місце для тих, хто мріє про власний будинок біля води — "
            "у тиші, з чистим повітрям та мальовничими пейзажами."
        ),
        "link_map": "https://www.google.com/maps?q=46.587795,30.885336",
        "link_youtube": None,
    },
    # ── Вапнярка VIP ──
    {
        "name": "Вапнярка VIP",
        "price": 1200,
        "plots_number": 48,
        "size": 6,
        "describe": (
            "Ділянки від 6 до 9 соток із краєвидом на лиман. "
            "Зручний асфальтований під'їзд забезпечує комфортний доїзд у будь-яку пору року. "
            "До масиву вже підведено воду та електропостачання.\n"
            "Ідеальне місце для тих, хто мріє про власний будинок біля води — "
            "у тиші, з чистим повітрям та мальовничими пейзажами."
        ),
        "link_map": "https://www.google.com/maps?q=46.587795,30.885336",
        "link_youtube": None,
    },
    # ── Фонтанка 1 ──
    {
        "name": "Фонтанка 1",
        "price": 870,
        "plots_number": 48,
        "size": 7,
        "describe": (
            "Перспективні ділянки поруч з асфальтною дорогою. "
            "Хороше розташування та чудова ціна для інвестицій або купівлі на майбутнє."
        ),
        "link_map": "https://www.google.com/maps?q=46.587392,30.859807",
        "link_youtube": None,
    },
    # ── Фонтанка 2 ──
    {
        "name": "Фонтанка 2",
        "price": 1300,
        "plots_number": 48,
        "size": 5,
        "describe": (
            "Ділянки прямокутної форми площею 5-7 соток. "
            "Є можливість придбання у розстрочку на 6 або 12 місяців під 0%. "
            "Ділянки межують із забудованим районом, що гарантує зручність "
            "та доступ до комунікацій.\n"
            "Чудовий варіант як для будівництва власного будинку, "
            "так і для вигідних інвестицій."
        ),
        "link_map": "https://www.google.com/maps?q=46.579168,30.872957",
        "link_youtube": None,
    },
]


async def seed():
    await init_db()
    async with async_session() as session:
        for data in REGIONS:
            session.add(Region(**data))
        await session.commit()
    print(f"Seeded {len(REGIONS)} regions.")


if __name__ == "__main__":
    asyncio.run(seed())
