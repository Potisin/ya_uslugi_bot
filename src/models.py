from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Order(Base):
    __tablename__ = 'Orders'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str]
    url: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str]
    contact: Mapped[str]
    is_invited: Mapped[bool] = mapped_column(default=False)
    is_tg_sent: Mapped[bool] = mapped_column(default=False)
