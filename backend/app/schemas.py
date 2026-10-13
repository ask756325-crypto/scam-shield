"""Request validation models."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)([a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}$")
_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._@:-]{1,255}$")
PLATFORMS = {"bluesky", "mastodon", "x", "instagram", "facebook", "tiktok", "youtube", "linkedin", "threads", "telegram", "other"}
STORES = {"apple", "google_play"}


def _clean_list(values: list[str], max_items: int, max_len: int) -> list[str]:
    out: list[str] = []
    for v in values:
        v = (v or "").strip()
        if not v:
            continue
        if len(v) > max_len:
            raise ValueError(f"Value too long (max {max_len} characters): {v[:30]}…")
        if v.lower() not in {o.lower() for o in out}:
            out.append(v)
    if len(out) > max_items:
        raise ValueError(f"At most {max_items} values allowed")
    return out


def _http_url(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip()
    parts = urlsplit(v)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Must be an http(s) URL")
    if len(v) > 500:
        raise ValueError("URL too long")
    return v


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=120)
    organization: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    remember: bool = False


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OfficialAccountIn(BaseModel):
    platform: str
    handle: str = Field(min_length=1, max_length=255)
    profile_url: str | None = None
    external_id: str | None = Field(default=None, max_length=255)

    @field_validator("platform")
    @classmethod
    def _platform(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in PLATFORMS:
            raise ValueError(f"Unsupported platform '{v}'")
        return v

    @field_validator("handle")
    @classmethod
    def _handle(cls, v: str) -> str:
        v = v.strip().lstrip("@").lower()
        if not _HANDLE_RE.match(v):
            raise ValueError("Handle contains invalid characters")
        return v

    @field_validator("profile_url")
    @classmethod
    def _url(cls, v):
        return _http_url(v)


class OfficialAppIn(BaseModel):
    store: str
    name: str | None = Field(default=None, max_length=255)
    app_id: str = Field(min_length=1, max_length=255)
    track_id: str | None = Field(default=None, max_length=64)
    publisher_id: str | None = Field(default=None, max_length=255)
    publisher_name: str | None = Field(default=None, max_length=255)
    url: str | None = None

    @field_validator("store")
    @classmethod
    def _store(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in STORES:
            raise ValueError("Store must be 'apple' or 'google_play'")
        return v

    @field_validator("app_id")
    @classmethod
    def _app_id(cls, v: str) -> str:
        v = v.strip()
        if not _PACKAGE_RE.match(v):
            raise ValueError("App ID must be a bundle/package identifier like com.example.app")
        return v

    @field_validator("track_id")
    @classmethod
    def _track(cls, v):
        if v is None or not str(v).strip():
            return None
        v = str(v).strip().removeprefix("id")
        if not v.isdigit():
            raise ValueError("Apple track ID must be numeric")
        return v

    @field_validator("publisher_id", "publisher_name", "name")
    @classmethod
    def _strip(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        return _http_url(v)


class BrandIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    aliases: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=4000)
    official_domains: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    website_url: str | None = None
    additional_identifiers: list[str] = Field(default_factory=list)
    official_accounts: list[OfficialAccountIn] = Field(default_factory=list, max_length=100)
    official_apps: list[OfficialAppIn] = Field(default_factory=list, max_length=100)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = re.sub(r"\s+", " ", v).strip()
        if len(v) < 2:
            raise ValueError("Brand name must be at least 2 characters")
        return v

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, v):
        return _clean_list(v, 20, 120)

    @field_validator("keywords")
    @classmethod
    def _keywords(cls, v):
        return _clean_list(v, 50, 120)

    @field_validator("additional_identifiers")
    @classmethod
    def _identifiers(cls, v):
        return _clean_list(v, 30, 200)

    @field_validator("website_url")
    @classmethod
    def _website(cls, v):
        return _http_url(v)

    @model_validator(mode="after")
    def _website_domain(self):
        # The primary website's host is official by definition: add it to the domain list if missing.
        if self.website_url:
            host = (urlsplit(self.website_url).hostname or "").lower().removeprefix("www.")
            if host and _DOMAIN_RE.match(host) and host not in self.official_domains:
                self.official_domains = [host, *self.official_domains]
        return self

    @field_validator("official_domains")
    @classmethod
    def _domains(cls, v):
        out = []
        for d in _clean_list(v, 50, 253):
            d = d.lower().strip()
            if "://" in d:
                d = urlsplit(d).hostname or ""
            d = d.strip("/").removeprefix("www.")
            if not _DOMAIN_RE.match(d):
                raise ValueError(f"Invalid domain: {d}")
            if d not in out:
                out.append(d)
        return out

    @model_validator(mode="after")
    def _unique_assets(self):
        seen = set()
        for a in self.official_accounts:
            k = (a.platform, a.handle)
            if k in seen:
                raise ValueError(f"Duplicate official account {a.platform}:@{a.handle}")
            seen.add(k)
        seen = set()
        for a in self.official_apps:
            k = (a.store, a.app_id.lower())
            if k in seen:
                raise ValueError(f"Duplicate official app {a.store}:{a.app_id}")
            seen.add(k)
        return self


class ScanIn(BaseModel):
    sources: list[str] | None = None  # default: all enabled sources (or demo for demo brands)


class DecisionIn(BaseModel):
    action: str
    note: str = Field(default="", max_length=2000)

    @field_validator("action")
    @classmethod
    def _action(cls, v: str) -> str:
        if v not in {"confirm", "mark_safe", "escalate", "reopen", "note"}:
            raise ValueError("Invalid action")
        return v


class ScheduleIn(BaseModel):
    frequency: str = "daily"
    interval_hours: int = 24
    time_of_day: str = "09:00"
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    timezone: str = Field(default="UTC", max_length=64)
    sources: list[str] | None = Field(default=None, max_length=10)


class MonitoringConfigIn(BaseModel):
    """Partial update: only the keys sent are changed (validated in services.org_settings)."""
    model_config = {"extra": "allow"}


class PurgeIn(BaseModel):
    confirm: str = ""


class SourceConfigIn(BaseModel):
    enabled_sources: list[str]
    mastodon_instances: list[str] = Field(default_factory=lambda: ["mastodon.social"], max_length=3)
    store_country: str = Field(default="us", pattern=r"^[a-zA-Z]{2}$")


class DetectionConfigIn(BaseModel):
    overrides: dict


class InviteIn(BaseModel):
    email: EmailStr
    role: str = "analyst"

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in {"analyst", "owner"}:
            raise ValueError("Role must be 'analyst' or 'owner'")
        return v


class AcceptInviteIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=120)


class ChangeEmailIn(BaseModel):
    new_email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class MemberRoleIn(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in {"analyst", "owner"}:
            raise ValueError("Role must be 'analyst' or 'owner'")
        return v


class ExclusionRulesIn(BaseModel):
    rules: dict[str, bool]


class RegistryCheckIn(BaseModel):
    """A hypothetical candidate to test against the brand's exclusion rules."""

    platform: str = Field(pattern=r"^(bluesky|mastodon|apple|google_play)$")
    handle: str | None = Field(default=None, max_length=255)
    profile_url: str | None = Field(default=None, max_length=500)
    account_id: str | None = Field(default=None, max_length=255)
    app_id: str | None = Field(default=None, max_length=255)
    track_id: str | None = Field(default=None, max_length=64)
    publisher_id: str | None = Field(default=None, max_length=255)
    verified_link: str | None = Field(default=None, max_length=500)
