"""Repository helpers for the local portfolio store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from amstock.models.store import StoreTransaction, StoreUser

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class StoreRepository:
    """Database access for local store entities."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_user_by_username(self, username: str) -> StoreUser | None:
        """Return a user by normalized username."""

        return self._session.scalar(select(StoreUser).where(StoreUser.username == username))

    def add_user(self, user: StoreUser) -> StoreUser:
        """Add a user to the current unit of work."""

        self._session.add(user)
        self._session.flush()
        return user

    def list_users(self, *, include_inactive: bool) -> list[StoreUser]:
        """List users ordered by username."""

        statement = select(StoreUser).order_by(StoreUser.username)
        if not include_inactive:
            statement = statement.where(StoreUser.is_active.is_(True))
        return list(self._session.scalars(statement))

    def add_transaction(self, transaction: StoreTransaction) -> StoreTransaction:
        """Add a transaction to the current unit of work."""

        self._session.add(transaction)
        self._session.flush()
        return transaction

    def get_transaction(self, *, user_id: int, transaction_id: int) -> StoreTransaction | None:
        """Return one transaction for a user."""

        return self._session.scalar(
            select(StoreTransaction).where(
                StoreTransaction.user_id == user_id,
                StoreTransaction.id == transaction_id,
            )
        )

    def delete_transaction(self, transaction: StoreTransaction) -> None:
        """Delete a transaction from the current unit of work."""

        self._session.delete(transaction)
        self._session.flush()

    def list_transactions(
        self,
        *,
        user_id: int,
        symbol: str | None = None,
    ) -> list[StoreTransaction]:
        """List transactions for one user in calculation order."""

        statement = (
            select(StoreTransaction)
            .where(StoreTransaction.user_id == user_id)
            .order_by(StoreTransaction.trade_date, StoreTransaction.id)
        )
        if symbol is not None:
            statement = statement.where(StoreTransaction.symbol == symbol)
        return list(self._session.scalars(statement))
