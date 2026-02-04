from __future__ import annotations

from decimal import Decimal

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Plot


class PlotsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_places_list(self, limit: int = 6) -> list[str]:
        result = await self._session.execute(
            select(distinct(Plot.place_name)).limit(limit)
        )
        return [row[0] for row in result.all()]

    async def get_plot(self, place_name: str, plot_number: str) -> Plot | None:
        result = await self._session.execute(
            select(Plot).where(
                Plot.place_name == place_name, Plot.plot_number == plot_number
            )
        )
        return result.scalar_one_or_none()

    async def create_plot(
        self,
        place_name: str,
        area_m2: int,
        price: Decimal,
        plot_number: str,
        is_sold: bool = False,
    ) -> Plot:
        plot = Plot(
            place_name=place_name,
            area_m2=area_m2,
            price=price,
            plot_number=plot_number,
            is_sold=is_sold,
        )
        self._session.add(plot)
        await self._session.commit()
        await self._session.refresh(plot)
        return plot

    async def set_sold(
        self, place_name: str, plot_number: str, is_sold: bool
    ) -> Plot | None:
        result = await self._session.execute(
            select(Plot).where(
                Plot.place_name == place_name, Plot.plot_number == plot_number
            )
        )
        plot = result.scalar_one_or_none()
        if plot is None:
            return None
        plot.is_sold = is_sold
        await self._session.commit()
        await self._session.refresh(plot)
        return plot
