"""FastAPI dependency wiring for the application persistence port."""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.contracts import UnitOfWork
from app.repositories.sqlalchemy import SqlAlchemyUnitOfWork


def get_unit_of_work(db: Session = Depends(get_db)) -> Generator[UnitOfWork, None, None]:
    yield SqlAlchemyUnitOfWork(db)


UnitOfWorkDependency = Annotated[UnitOfWork, Depends(get_unit_of_work)]
