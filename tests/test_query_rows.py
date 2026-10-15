"""get_owned_or_404: a row by primary key or a 404, and with `owner` someone
else's row is the same 404 as a missing one."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import Integer, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from greentechhub_fastapi import register_api_error_handlers
from greentechhub_fastapi.query import get_owned_or_404


class Base(DeclarativeBase):
    pass


class Stock(Base):
    __tablename__ = "stocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String)
    account: Mapped[str] = mapped_column(String, default="")


class Holding(Base):
    __tablename__ = "holdings"
    portfolio: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[str] = mapped_column(String)


@pytest.fixture
def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rows.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session, session.begin():
            session.add_all([
                Stock(id=1, symbol="ASX"),
                Transaction(id=1, user_id="alice", account="joint"),
                Transaction(id=2, user_id="bob"),
                Holding(portfolio="main", symbol="ASX", owner="alice"),
            ])

    asyncio.run(setup())
    yield factory
    asyncio.run(engine.dispose())


def _get(factory, *args, **kwargs):
    async def go():
        async with factory() as session:
            return await get_owned_or_404(session, *args, **kwargs)

    return asyncio.run(go())


def test_a_row_without_an_owner(sessions):
    assert _get(sessions, Stock, 1).symbol == "ASX"
    with pytest.raises(HTTPException) as missing:
        _get(sessions, Stock, 99)
    assert (missing.value.status_code, missing.value.detail) == (404, "Stock not found")


def test_someone_elses_row_is_the_same_404_as_a_missing_one(sessions):
    assert _get(sessions, Transaction, 1, owner="alice").user_id == "alice"
    details = []
    for txn_id in (2, 99):  # bob's, and nobody's
        with pytest.raises(HTTPException) as exc:
            _get(sessions, Transaction, txn_id, owner="alice")
        details.append((exc.value.status_code, exc.value.detail))
    assert details == [(404, "Transaction not found")] * 2


def test_a_custom_owner_field_and_detail(sessions):
    assert _get(sessions, Transaction, 1, owner="joint", owner_field="account").id == 1
    with pytest.raises(HTTPException) as exc:
        _get(sessions, Transaction, 2, owner="joint", owner_field="account",
             detail="No such transaction.")
    assert exc.value.detail == "No such transaction."


def test_a_model_without_the_owner_field_is_a_programming_error(sessions):
    with pytest.raises(AttributeError, match="Stock has no owner field 'user_id'"):
        _get(sessions, Stock, 1, owner="alice")


def test_a_composite_key(sessions):
    holding = _get(sessions, Holding, ("main", "ASX"), owner="alice", owner_field="owner")
    assert holding.symbol == "ASX"
    with pytest.raises(HTTPException):
        _get(sessions, Holding, ("main", "ASX"), owner="bob", owner_field="owner")


def test_an_api_route_answers_with_the_not_found_envelope(sessions):
    app = FastAPI()
    register_api_error_handlers(app)

    @app.get("/api/transactions/{txn_id}")
    async def transaction(txn_id: int):
        async with sessions() as session:
            txn = await get_owned_or_404(session, Transaction, txn_id, owner="alice")
        return {"id": txn.id}

    async def go(path):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    assert asyncio.run(go("/api/transactions/1")).json() == {"id": 1}
    theirs = asyncio.run(go("/api/transactions/2"))
    assert theirs.status_code == 404
    assert theirs.json()["code"] == "not_found"
    assert theirs.json()["message"] == "Transaction not found"
