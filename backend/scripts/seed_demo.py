"""Create a local demo account + the synthetic demo brand, and run one demo scan.

Usage (from backend/):  .venv/Scripts/python scripts/seed_demo.py   (Windows)
                        .venv/bin/python scripts/seed_demo.py       (macOS/Linux)

Credentials come from SEED_EMAIL / SEED_PASSWORD / SEED_NAME / SEED_ORG in the environment, falling back
to backend/.env.example. Intended for local development only; refuses to run when SCAMSHIELD_ENV=production.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_seed_values() -> dict[str, str]:
    values: dict[str, str] = {}
    example = ROOT / ".env.example"
    if example.exists():
        for line in example.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    for k in ("SEED_EMAIL", "SEED_PASSWORD", "SEED_NAME", "SEED_ORG"):
        if os.environ.get(k):
            values[k] = os.environ[k]
    return values


def main() -> None:
    from sqlalchemy import func, select

    from app.config import get_settings
    from app.db import SessionLocal, init_db
    from app.demo.assets import asset_path, ensure_assets
    from app.demo.dataset import DEMO_BRAND
    from app.models import Brand, Membership, Organization, User
    from app.routers.brands import _apply, _store_logo
    from app.schemas import BrandIn
    from app.security import hash_password, password_problems
    from app.services import scanner

    if not get_settings().is_dev:
        sys.exit("Refusing to seed outside development (SCAMSHIELD_ENV must be development).")
    v = load_seed_values()
    email, password = v.get("SEED_EMAIL", "").lower(), v.get("SEED_PASSWORD", "")
    if not email or not password:
        sys.exit("Set SEED_EMAIL and SEED_PASSWORD (see backend/.env.example).")
    if problems := password_problems(password, email):
        sys.exit("Seed password rejected: " + " ".join(problems))

    init_db()
    ensure_assets()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user:
            org = db.scalar(select(Membership).where(Membership.user_id == user.id)).organization
            print(f"User {email} already exists (organization: {org.name}).")
        else:
            user = User(email=email, name=v.get("SEED_NAME", "Demo Analyst"), password_hash=hash_password(password))
            org = Organization(name=v.get("SEED_ORG", "Demo Organization"), detection_config={}, source_config={})
            db.add_all([user, org])
            db.flush()
            db.add(Membership(user_id=user.id, organization_id=org.id, role="owner"))
            db.commit()
            print(f"Created user {email} in organization “{org.name}”.")
        brand = db.scalar(select(Brand).where(Brand.organization_id == org.id, Brand.is_demo.is_(True)))
        if not brand:
            brand = Brand(organization_id=org.id, is_demo=True)
            _apply(brand, BrandIn(
                name=DEMO_BRAND["name"], aliases=DEMO_BRAND["aliases"], description=DEMO_BRAND["description"],
                official_domains=DEMO_BRAND["official_domains"], keywords=DEMO_BRAND["keywords"], website_url=DEMO_BRAND["website_url"], additional_identifiers=DEMO_BRAND["additional_identifiers"],
                official_accounts=DEMO_BRAND["official_accounts"], official_apps=DEMO_BRAND["official_apps"],
            ))
            db.add(brand)
            db.commit()
            _store_logo(db, brand, asset_path(DEMO_BRAND["logo_asset"]).read_bytes())
            print(f"Created demo brand “{brand.name}” (synthetic).")
        scan = scanner.create_scan(db, brand, ["demo"], "manual", user.id)
        scan_id = scan.id
    asyncio.run(scanner.run_scan(scan_id))
    with SessionLocal() as db:
        from app.models import Scan

        s = db.get(Scan, scan_id)
        print(f"Demo scan #{s.id}: {s.status} · {s.candidates_unique} candidates · {s.excluded_official} official excluded · {s.findings_new} new findings")
    print("Sign in at http://localhost:3000/signin with the SEED_EMAIL / SEED_PASSWORD values from backend/.env.example.")


if __name__ == "__main__":
    main()
