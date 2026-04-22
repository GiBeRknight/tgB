from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_realtor: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Realtor(Base):
    __tablename__ = "realtors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    password: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    plots_number: Mapped[int] = mapped_column(Integer)
    describe: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_map: Mapped[str | None] = mapped_column(String(500), nullable=True)
    size: Mapped[float] = mapped_column(Numeric(10, 2), default=5)
    link_youtube: Mapped[str | None] = mapped_column(String(500), nullable=True)
    link_doc: Mapped[str | None] = mapped_column(String(500), nullable=True)
    doc_file_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    doc_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scheme_photo_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("region_groups.id", ondelete="SET NULL"), nullable=True
    )


class RegionGroup(Base):
    __tablename__ = "region_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(255), unique=True)
    prefix: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RegionPhoto(Base):
    __tablename__ = "region_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    region_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("regions.id", ondelete="CASCADE")
    )
    file_id: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(20), default="photo")
    position: Mapped[int] = mapped_column(Integer, default=0)
