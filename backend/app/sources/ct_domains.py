"""Look-alike domains from Certificate Transparency logs via crt.sh (public, unauthenticated).

Every publicly trusted TLS certificate is logged in CT. Phishing sites need certificates too, so newly issued
certificates for hostnames containing the brand name are an early signal of look-alike domains.

* Query: crt.sh JSON search for hostnames containing the compact brand token (`%acmewallet%`).
* Only certificates issued within `LOOKBACK_DAYS` are kept; hostnames are de-duplicated; wildcards are stripped.
* crt.sh is a free community service that is often slow or briefly unavailable — failures are reported as such and
  never replaced by synthetic data. Requests are spaced and bounded.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import httpx

from ..candidate import CandidateRecord
from ..detection.urls import registrable_domain
from .base import SourceAdapter, SourceError, SourceInfo, get_json

ENDPOINT = "https://crt.sh/"
LOOKBACK_DAYS = 120
MAX_HOSTS_PER_QUERY = 150
_HOST_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$")


class CTDomainsAdapter(SourceAdapter):
    info = SourceInfo(
        name="ct_domains",
        label="Look-alike domains (CT logs)",
        category="web",
        source_type="live",
        integration="crt.sh Certificate Transparency search (JSON), unauthenticated",
        reliability="official public API",
        docs_url="https://crt.sh/",
        notes=f"Finds hostnames containing the brand name in TLS certificates issued in the last {LOOKBACK_DAYS} days. "
              "crt.sh is a free community service and is sometimes slow or unavailable; domains are analysed as text only and never visited.",
        auth="none",
        rate_limit="No published quota; ScamShield spaces requests 5 s apart and limits queries per scan.",
    )
    max_results_per_query = MAX_HOSTS_PER_QUERY
    min_interval_seconds = 5.0

    @staticmethod
    def token(term: str) -> str:
        return re.sub(r"[^a-z0-9]", "", term.lower())

    async def search(self, term: str, client: httpx.AsyncClient) -> list[CandidateRecord]:
        token = self.token(term)
        if len(token) < 5:
            return []  # too short to search CT without flooding results; counted as a genuine empty result
        data = await get_json(client, ENDPOINT, {"q": f"%{token}%", "output": "json", "exclude": "expired"}, "ct_domains", adapter=self)
        if not isinstance(data, list):
            raise SourceError("ct_domains returned an unexpected payload", "error")
        return self.normalize_all(data, term, token)

    @staticmethod
    def normalize_all(entries: list[dict], term: str, token: str, now: datetime | None = None) -> list[CandidateRecord]:
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=LOOKBACK_DAYS)
        hosts: dict[str, dict] = {}
        for e in entries:
            try:
                issued = datetime.fromisoformat(str(e.get("not_before", "")).replace("Z", "")).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if issued < cutoff:
                continue
            names = {str(e.get("common_name") or "")} | set(str(e.get("name_value") or "").split("\n"))
            for raw in names:
                host = raw.strip().lower().removeprefix("*.").rstrip(".")
                if not host or token not in re.sub(r"[^a-z0-9]", "", host) or not _HOST_RE.match(host):
                    continue
                h = hosts.setdefault(host, {"first": issued, "issuers": set(), "cert_ids": []})
                h["first"] = min(h["first"], issued)
                issuer = re.search(r"O=([^,]+)", str(e.get("issuer_name") or ""))
                if issuer:
                    h["issuers"].add(issuer.group(1).strip().strip('"'))
                if e.get("id") and len(h["cert_ids"]) < 5:
                    h["cert_ids"].append(e["id"])
        out = []
        for host, h in sorted(hosts.items(), key=lambda kv: kv[1]["first"], reverse=True)[:MAX_HOSTS_PER_QUERY]:
            issuers = ", ".join(sorted(h["issuers"])) or "unknown CA"
            out.append(CandidateRecord(
                source="ct_domains", source_type="live", kind="domain", external_id=host, name=host,
                url=f"https://{host}",
                description=f"TLS certificate for {host} first issued {h['first'].date().isoformat()} by {issuers}.",
                metadata={"platform": "domain", "registrable_domain": registrable_domain(host), "first_certificate_at": h["first"].isoformat(),
                          "issuers": sorted(h["issuers"]), "certificate_ids": h["cert_ids"]},
                source_created_at=h["first"].isoformat(),
                provenance={"adapter": "ct_domains", "endpoint": ENDPOINT, "query": term},
            ))
        return out
