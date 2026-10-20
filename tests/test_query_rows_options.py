"""get_owned_or_404(options=): loader options for session.get, so a
relationship a route reads arrives loaded. An AsyncSession can't lazy-load
it later (MissingGreenlet)."""

import asyncio

import pytest
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.exc import MissingGreenlet, StatementError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

from greentechhub_fastapi.query import get_owned_or_404


class Base(DeclarativeBase):
    pass


class Stock(Base):
    __tablename__ = "stocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String)


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    stock: Mapped[Stock] = relationship()


@pytest.fixture
def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'options.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as session, session.begin():
            session.add_all([Stock(id=1, symbol="BHP"), Trade(id=1, user_id="alice", stock_id=1)])

    asyncio.run(setup())
    yield sessions
    asyncio.run(engine.dispose())


def test_options_load_a_relationship_the_route_reads(factory):
    async def go():
        async with factory() as session:
            trade = await get_owned_or_404(session, Trade, 1, owner="alice",
                                           options=[selectinload(Trade.stock)])
            return trade.stock.symbol

    assert asyncio.run(go()) == "BHP"


def test_without_options_the_relationship_cant_lazy_load(factory):
    async def go():
        async with factory() as session:
            trade = await get_owned_or_404(session, Trade, 1, owner="alice")
            return trade.stock.symbol

    with pytest.raises((MissingGreenlet, StatementError), match="greenlet_spawn"):  # 2.1 wraps it
        asyncio.run(go())


def test_options_keep_the_owner_check(factory):
    from fastapi import HTTPException

    async def go():
        async with factory() as session:
            await get_owned_or_404(session, Trade, 1, owner="bob",
                                   options=[selectinload(Trade.stock)])

    with pytest.raises(HTTPException) as exc:
        asyncio.run(go())
    assert (exc.value.status_code, exc.value.detail) == (404, "Trade not found")
