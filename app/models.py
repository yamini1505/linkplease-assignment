from sqlalchemy import Column, String, Integer, UniqueConstraint

from .database import Base


class Rule(Base):
    __tablename__ = "rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(String, unique=True, index=True)
    keyword = Column(String, index=True)
    dm_message = Column(String)


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)

    rule_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    comment_id = Column(String, index=True, nullable=False)

    status = Column(String, default="queued")
    dm_id = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "rule_id",
            "user_id",
            name="uq_rule_user"
        ),
    )

class Stats(Base):
    __tablename__ = "stats"

    id = Column(Integer, primary_key=True)
    duplicates_blocked = Column(Integer, default=0)