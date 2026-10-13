"""ORM models. Every tenant-owned row is reachable from an Organization; access is checked via org membership."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TZDateTime(TypeDecorator):
    """DateTime that always round-trips as timezone-aware UTC (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, datetime) and value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
            if dialect.name == "sqlite":
                value = value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if isinstance(value, datetime):
            # SQLite returns naive UTC; PostgreSQL returns the session time zone. Always hand back UTC.
            value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value


# --------------------------------------------------------------------------- identity


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    # Per-organization overrides of detection weights/thresholds (merged over defaults).
    detection_config: Mapped[dict] = mapped_column(JSON, default=dict)
    # Source configuration: enabled sources, Mastodon instances, store country.
    source_config: Mapped[dict] = mapped_column(JSON, default=dict)
    # Monitoring rules, e.g. {"resolve_after_misses": 2}.
    monitoring_config: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    # Webhook alert channel: {"url": ..., "enabled": bool, "events": [...]}. The URL is a secret (it embeds a token).
    notification_config: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    memberships: Mapped[list[Membership]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    # Two-factor authentication (TOTP). The secret authenticates the user, so it is never returned after setup.
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_pending_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    totp_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)  # replay protection
    recovery_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)  # sha256 hashes of unused codes

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")  # owner | analyst
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship(back_populates="memberships")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 of opaque token
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship()


class EmailVerification(Base):
    __tablename__ = "email_verifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(254))  # the address being verified (guards against later email changes)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class PasswordReset(Base):
    __tablename__ = "password_resets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


# --------------------------------------------------------------------------- brand profile


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    official_domains: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)  # product names, taglines
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Reference identifiers (legal entity names, trademark/registration numbers). Similarity corpus only.
    additional_identifiers: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)
    # Per-brand overrides of detection.exclusion.EXCLUSION_RULES ({rule_id: bool}); owners only.
    exclusion_rules: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    logo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_phash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    logo_dhash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Legacy schedule fields (pre-MonitoringSchedule); migrated at startup and no longer written.
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    next_scheduled_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    official_accounts: Mapped[list[OfficialAccount]] = relationship(
        back_populates="brand", cascade="all, delete-orphan", order_by="OfficialAccount.id"
    )
    official_apps: Mapped[list[OfficialApp]] = relationship(
        back_populates="brand", cascade="all, delete-orphan", order_by="OfficialApp.id"
    )
    schedule: Mapped[MonitoringSchedule | None] = relationship(back_populates="brand", cascade="all, delete-orphan", uselist=False)


class OfficialAccount(Base):
    __tablename__ = "official_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(40))  # bluesky | mastodon | x | instagram | ...
    handle: Mapped[str] = mapped_column(String(255))  # canonical, lowercased, no leading @
    profile_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # e.g. Bluesky DID

    brand: Mapped[Brand] = relationship(back_populates="official_accounts")


class OfficialApp(Base):
    __tablename__ = "official_apps"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    store: Mapped[str] = mapped_column(String(20))  # apple | google_play
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)  # listing title (reference only)
    app_id: Mapped[str] = mapped_column(String(255))  # bundle id or package name
    track_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Apple numeric id
    publisher_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    publisher_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    brand: Mapped[Brand] = relationship(back_populates="official_apps")


# --------------------------------------------------------------------------- scanning


class Scan(Base):
    __tablename__ = "scans"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual | scheduled
    mode: Mapped[str] = mapped_column(String(20), default="live")  # live | demo
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|completed|partial|failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1, computed from completed work units
    stage: Mapped[str] = mapped_column(String(120), default="Queued")
    search_terms: Mapped[list] = mapped_column(JSON, default=list)
    candidates_collected: Mapped[int] = mapped_column(Integer, default=0)
    candidates_unique: Mapped[int] = mapped_column(Integer, default=0)
    excluded_official: Mapped[int] = mapped_column(Integer, default=0)
    findings_new: Mapped[int] = mapped_column(Integer, default=0)
    findings_changed: Mapped[int] = mapped_column(Integer, default=0)
    findings_recurring: Mapped[int] = mapped_column(Integer, default=0)
    findings_resolved: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Findings not observed although their source completed cleanly (below the resolution threshold).
    findings_missing: Mapped[int] = mapped_column(Integer, default=0)
    # Findings whose source failed or was incomplete in this scan: absence is unknown, nothing is resolved.
    findings_unverified: Mapped[int] = mapped_column(Integer, default=0)
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("monitoring_schedules.id", ondelete="SET NULL"), nullable=True, index=True)
    runner: Mapped[str | None] = mapped_column(String(40), nullable=True)  # process role that executes it (api | worker)
    heartbeat_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    # At most one queued/running scan per brand, enforced by the database (no duplicate concurrent scans,
    # even across API and worker processes).
    __table_args__ = (
        Index(
            "uq_scans_one_active_per_brand", "brand_id", unique=True,
            sqlite_where=text("status IN ('queued', 'running')"), postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    sources: Mapped[list[ScanSource]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", order_by="ScanSource.id"
    )
    brand: Mapped[Brand] = relationship()


class ScanSource(Base):
    __tablename__ = "scan_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|ok|partial|failed|skipped
    queries_total: Mapped[int] = mapped_column(Integer, default=0)
    queries_done: Mapped[int] = mapped_column(Integer, default=0)
    queries_failed: Mapped[int] = mapped_column(Integer, default=0)
    candidates: Mapped[int] = mapped_column(Integer, default=0)
    # Per-query outcome counts: ok | empty | rate_limited | timeout | unavailable | auth_required | error
    query_outcomes: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)  # dominant failure reason
    rate_limit: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # last observed rate-limit headers
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    scan: Mapped[Scan] = relationship(back_populates="sources")


class Candidate(Base):
    """A deduplicated external account/app observed for a brand (unique per brand+source+external id)."""

    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("brand_id", "source", "external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(40))  # bluesky | mastodon | apple_app_store | google_play | ...
    source_type: Mapped[str] = mapped_column(String(20))  # live | simulated | imported
    kind: Mapped[str] = mapped_column(String(20))  # account | app
    external_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(500), default="")
    handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    publisher_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    publisher_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_links: Mapped[list] = mapped_column(JSON, default=list)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)  # source-specific metadata
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)  # endpoint, query, adapter version
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    first_observed_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    last_observed_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    source_created_at: Mapped[str | None] = mapped_column(String(64), nullable=True)

    finding: Mapped[Finding | None] = relationship(back_populates="candidate", uselist=False)


class Observation(Base):
    """One sighting of a candidate in one scan; used for new/changed/recurring/resolved comparisons."""

    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


# Statuses that still need analyst attention (review queue, open counts).
REVIEW_STATUSES = ("open", "escalated")


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), unique=True)
    risk_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(20))  # critical | high | medium | low | info
    classification: Mapped[str] = mapped_column(String(120))
    # fake_brand_page | fake_profile | scam_account | lookalike_account | suspicious_app | lookalike_app | unrelated
    detection_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    explanation: Mapped[str] = mapped_column(Text)
    signals: Mapped[dict] = mapped_column(JSON, default=dict)  # name -> {score, evaluated, detail}
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    corroborating_groups: Mapped[list] = mapped_column(JSON, default=list)
    # Analyst workflow: open | confirmed | safe | resolved
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | escalated | confirmed | safe | resolved
    # Comparison with prior observation: new | changed | recurring | resolved
    change_state: Mapped[str] = mapped_column(String(20), default="new")  # new | changed | recurring | missing | resolved
    # Consecutive clean scans of the finding's source that did not observe it (reset when observed).
    missed_scans: Mapped[int] = mapped_column(Integer, default=0)
    # Analyst responsible for reviewing this finding (optional).
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    first_seen_scan_id: Mapped[int | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)
    last_seen_scan_id: Mapped[int | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    candidate: Mapped[Candidate] = relationship(back_populates="finding")
    decisions: Mapped[list[Decision]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", order_by="Decision.created_at"
    )


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(20))  # confirm | mark_safe | escalate | reopen | note
    note: Mapped[str] = mapped_column(Text, default="")
    # Status transition recorded with the decision (audit trail); equal for notes.
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    finding: Mapped[Finding] = relationship(back_populates="decisions")
    user: Mapped[User | None] = relationship()


class Exclusion(Base):
    """Audit trail of official assets excluded before scoring."""

    __tablename__ = "exclusions"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    rule: Mapped[str] = mapped_column(String(60))
    matched_value: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class Invite(Base):
    """Single-use, expiring invitation to join an organization."""

    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    role: Mapped[str] = mapped_column(String(20), default="analyst")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    accepted_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class MonitoringSchedule(Base):
    """Recurring scan configuration for one brand. Times are computed in `timezone` and stored in UTC."""

    __tablename__ = "monitoring_schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), unique=True)
    state: Mapped[str] = mapped_column(String(20), default="active")  # active | paused | disabled
    frequency: Mapped[str] = mapped_column(String(20), default="daily")  # interval | daily | weekly
    interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    time_of_day: Mapped[str] = mapped_column(String(5), default="09:00")  # HH:MM local time (daily/weekly)
    weekdays: Mapped[list] = mapped_column(JSON, default=list)  # 0=Mon … 6=Sun (weekly)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")  # IANA name
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)  # None = all enabled sources
    next_run_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_scan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)  # completed|partial|failed|skipped_overlap|deferred|error
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    paused_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)  # compare-and-set claim token
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    brand: Mapped[Brand] = relationship(back_populates="schedule")


class FindingChange(Base):
    """What a scan concluded about one finding: new, changed (with field diff), recurring, missing, resolved, reappeared."""

    __tablename__ = "finding_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    change: Mapped[str] = mapped_column(String(20))
    changed_fields: Mapped[list] = mapped_column(JSON, default=list)
    previous: Mapped[dict] = mapped_column(JSON, default=dict)  # prior values of changed fields (truncated)
    current: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_before: Mapped[str | None] = mapped_column(String(20), nullable=True)
    risk_after: Mapped[str | None] = mapped_column(String(20), nullable=True)
    missed_scans: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class RuntimeState(Base):
    """Small key/value store for process heartbeats (e.g. the scheduler's last tick), visible to every process."""

    __tablename__ = "runtime_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class SourceCheck(Base):
    """A genuine connectivity test of one source (one real query), kept as history per organization."""

    __tablename__ = "source_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    # ok | empty | rate_limited | timeout | unavailable | auth_required | error | invalid_config
    outcome: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(Text, default="")
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class NotificationPreference(Base):
    """Per-user email alert preferences within one organization."""

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "organization_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email_new_critical: Mapped[bool] = mapped_column(Boolean, default=True)
    email_new_high: Mapped[bool] = mapped_column(Boolean, default=False)
    email_source_failure: Mapped[bool] = mapped_column(Boolean, default=True)
    digest: Mapped[str] = mapped_column(String(10), default="off")  # off | daily
    digest_hour: Mapped[int] = mapped_column(Integer, default=8)  # local hour 0-23
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    last_digest_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class NotificationLog(Base):
    """Every notification attempt and its real outcome (sent | logged | skipped | failed)."""

    __tablename__ = "notification_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20))  # email | webhook
    event: Mapped[str] = mapped_column(String(40))  # new_threat | source_failure | schedule_paused | digest | test
    recipient: Mapped[str] = mapped_column(String(255), default="")  # masked
    subject: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(Text, default="")
    scan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)


class AuditEvent(Base):
    """Organization audit log: who changed what (configuration, access, data management, exports)."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email: Mapped[str] = mapped_column(String(255), default="")  # kept if the user is later removed
    action: Mapped[str] = mapped_column(String(60), index=True)  # e.g. sources.config_updated
    target_type: Mapped[str] = mapped_column(String(40), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    summary: Mapped[str] = mapped_column(String(500), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)  # never contains secrets
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)


class TakedownCase(Base):
    """Tracks reporting a confirmed impersonation to the platform. ScamShield never files reports itself."""

    __tablename__ = "takedown_cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), unique=True)
    platform: Mapped[str] = mapped_column(String(40))
    channel_label: Mapped[str] = mapped_column(String(200), default="")
    channel_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|reported|acknowledged|removed|rejected|withdrawn
    reference: Mapped[str] = mapped_column(String(200), default="")  # platform ticket / case number
    report_text: Mapped[str] = mapped_column(Text, default="")
    events: Mapped[list] = mapped_column(JSON, default=list)  # [{at, status, note, user}]
    verification: Mapped[str] = mapped_column(String(30), default="unknown")  # unknown | still_observed | not_observed | reappeared
    verified_scan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reported_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class LoginChallenge(Base):
    """A password-verified login waiting for its second factor. Short-lived, single-use, attempt-limited."""

    __tablename__ = "login_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    remember: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class RateLimitEvent(Base):
    """One counted attempt for the shared (database-backed) rate limiter. Keys are hashed — no emails or IPs stored."""

    __tablename__ = "rate_limit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[float] = mapped_column(Float, index=True)  # unix time
