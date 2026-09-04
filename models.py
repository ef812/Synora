import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _now():
    return datetime.now(timezone.utc)


class EmployeeProfile(Base):
    """Workplace context for the employee tier. One row per Clerk user.
    Re-asked periodically (see context_last_updated) rather than collected once."""

    __tablename__ = "employee_profiles"

    user_id = Column(String, primary_key=True)  # Clerk user_id
    job_role = Column(String, nullable=True)
    work_schedule = Column(String, nullable=True)  # e.g. "standard" | "shift" | "remote" | "hybrid"

    # Stress factors, each 1-5. Stored as JSON rather than separate columns
    # so we can add new factors later without a migration.
    stress_factors = Column(JSON, default=dict)  # {"workload": 3, "hours": 4, "physical_strain": 2}

    checkin_interval_days = Column(Integer, default=7)  # user-configurable

    context_last_updated = Column(DateTime(timezone=True), default=_now)
    created_at = Column(DateTime(timezone=True), default=_now)

    checkins = relationship("CheckinEntry", back_populates="profile", order_by="desc(CheckinEntry.created_at)")

    def context_is_stale(self, staleness_days: int = 90) -> bool:
        """True once workplace context is old enough to re-ask (default ~3 months)."""
        age = _now() - self.context_last_updated.replace(tzinfo=timezone.utc)
        return age.days >= staleness_days


class CheckinEntry(Base):
    """A single recurring check-in submission."""

    __tablename__ = "checkin_entries"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("employee_profiles.user_id"), nullable=False, index=True)

    energy = Column(Integer, nullable=True)   # 1-5
    stress = Column(Integer, nullable=True)   # 1-5
    sleep = Column(Integer, nullable=True)    # 1-5
    new_symptoms = Column(String, nullable=True)  # optional free text

    linked_analysis_id = Column(String, nullable=True)  # set if this check-in triggered a full pipeline run

    created_at = Column(DateTime(timezone=True), default=_now)

    profile = relationship("EmployeeProfile", back_populates="checkins")
