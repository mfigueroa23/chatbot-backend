from datetime import time
from sqlalchemy import CheckConstraint, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class ServiceSchedule(Base):
    __tablename__ = "service_schedule"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="service_schedule_weekday_check"),
        CheckConstraint("opens_at < closes_at", name="service_schedule_hours_check"),
    )

    # 0 = lunes … 6 = domingo, igual que datetime.weekday().
    weekday: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    opens_at: Mapped[time]
    closes_at: Mapped[time]
