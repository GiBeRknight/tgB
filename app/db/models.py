from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Plot(Base):
    __tablename__ = "plots"
    __table_args__ = (
        UniqueConstraint("place_name", "plot_number", name="uq_plots_place_plot_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    place_name: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    area_m2: Mapped[int] = mapped_column(Integer, nullable=False)
    # Храним цену в денежных единицах с фиксированной точностью (копейки/центы) через Numeric.
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    plot_number: Mapped[str] = mapped_column(String(32), nullable=False)
    is_sold: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

    def __repr__(self) -> str:
        return (
            "Plot(id={id}, place_name={place_name!r}, plot_number={plot_number!r}, "
            "area_m2={area_m2}, price={price}, is_sold={is_sold})"
        ).format(
            id=self.id,
            place_name=self.place_name,
            plot_number=self.plot_number,
            area_m2=self.area_m2,
            price=self.price,
            is_sold=self.is_sold,
        )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    telegram_id: Mapped[int | None] = mapped_column(
        BigInteger, unique=True, index=True, nullable=True
    )
    remember_login: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False
    )

    def __repr__(self) -> str:
        return (
            "User(id={id}, username={username!r}, is_admin={is_admin}, "
            "telegram_id={telegram_id})"
        ).format(
            id=self.id,
            username=self.username,
            is_admin=self.is_admin,
            telegram_id=self.telegram_id,
        )
