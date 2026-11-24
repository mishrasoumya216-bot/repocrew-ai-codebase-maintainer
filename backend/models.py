"""RepoCrew ORM models (SQLite today, Postgres-compatible schema)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, JSON, ForeignKey
from sqlalchemy.ext.hybrid import hybrid_property

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StatusString(str):
    """String subclass allowing 'STOPPED_NEEDS_HUMAN' and 'needs-human' to match interchangeably."""
    def __eq__(self, other: object) -> bool:
        if super().__eq__(other):
            return True
        if self in ("STOPPED_NEEDS_HUMAN", "needs-human") and other in ("STOPPED_NEEDS_HUMAN", "needs-human"):
            return True
        return False


class Issue(Base):
    __tablename__ = "issues"

    id = Column(Integer, primary_key=True)
    number = Column(Integer, unique=True, nullable=False, index=True)
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=False, default="")
    labels = Column(JSON, nullable=False, default=list)  # list[str]
    reporter = Column(String(120), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=utcnow)


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True)
    issue_id = Column(Integer, ForeignKey("issues.id"), nullable=False, index=True)
    _status = Column("status", String(40), nullable=False, default="QUEUED", index=True)

    @hybrid_property
    def status(self) -> str:
        val = self._status
        return StatusString(val) if val is not None else "QUEUED"

    @status.setter
    def status(self, val: str) -> None:
        if val == "needs-human":
            val = "STOPPED_NEEDS_HUMAN"
        self._status = val

    @status.expression
    def status(cls):
        return cls._status

    mode = Column(String(10), nullable=False, default="demo")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    current_agent = Column(String(20), nullable=False, default="orchestrator")
    agent_states = Column(JSON, nullable=False, default=dict)  # {"triage": "passed", ...}
    triage_result = Column(JSON, nullable=True)
    reviews = Column(JSON, nullable=False, default=list)
    gate_result = Column(JSON, nullable=True)
    pr_title = Column(String(300), nullable=True)
    pr_body = Column(Text, nullable=True)
    human_comment = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False, index=True)
    ts = Column(Float, nullable=False)  # epoch seconds (float for sub-second resolution)
    agent = Column(String(20), nullable=False)  # orchestrator|triage|coder|tester|reviewer|gate
    type = Column(String(20), nullable=False)   # step|message|tool_call|tool_result|status|log
    text = Column(Text, nullable=False, default="")
    data = Column(JSON, nullable=True)


class Patch(Base):
    __tablename__ = "patches"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False, index=True)
    attempt = Column(Integer, nullable=False)
    diff = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class TestResult(Base):
    __tablename__ = "test_results"
    __test__ = False  # not a pytest test class

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False, index=True)
    attempt = Column(Integer, nullable=False)
    passed = Column(Boolean, nullable=False, default=False)
    total = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    passed_count = Column(Integer, nullable=False, default=0)
    raw_output = Column(Text, nullable=False, default="")
    detail = Column(Text, nullable=False, default="")
    engine = Column(String(20), nullable=False, default="local")  # docker | local
    created_at = Column(DateTime, nullable=False, default=utcnow)
    reproduced = Column(Boolean, nullable=False, default=False)
    test_name = Column(String(300), nullable=True)

    @property
    def repro_test(self) -> str | None:
        return self.test_name

    @repro_test.setter
    def repro_test(self, val: str | None) -> None:
        self.test_name = val


# Alias TesterResult for TestResult as required by RepoCrew models schema
TesterResult = TestResult


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False, index=True)
    issue_id = Column(Integer, ForeignKey("issues.id"), nullable=False)
    kind = Column(String(20), nullable=False, default="preview")  # github | preview
    url = Column(String(500), nullable=True)
    branch = Column(String(200), nullable=True)
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
