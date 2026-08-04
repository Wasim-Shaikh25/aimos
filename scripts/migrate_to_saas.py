#!/usr/bin/env python
"""Migrate an existing single-user AIMOS deployment to the SaaS tenant model.

What it does:
- Creates the auth/tenant database tables.
- Creates a default organization (id = ``local``).
- Optionally creates the first owner user (email + password) if provided.
- Moves the existing single-user journal ``state/aimos.sqlite`` to the
  per-tenant path ``state/journals/local.sqlite``.
- Prints the env vars needed to run the SaaS-enabled trading loop.

Run once before starting with ``features.saas_enabled: true``:

    python -m scripts.migrate_to_saas \
        --admin-email admin@example.com --admin-password "CHANGEME"

"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from aimos.saas.db import get_engine, get_session_maker
from aimos.saas.models import Organization, OrganizationConfig, OrganizationMember, User
from aimos.saas.security import hash_password


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Migrate single-user AIMOS to SaaS tenant model")
    ap.add_argument("--org-id", default="local", help="tenant id for the default org")
    ap.add_argument("--org-name", default="Default", help="display name for the default org")
    ap.add_argument("--org-slug", default="default", help="slug for the default org")
    ap.add_argument("--admin-email", help="create an owner user with this email")
    ap.add_argument("--admin-password", help="initial password for the owner user")
    ap.add_argument("--state-dir", default="state", help="root state directory")
    ap.add_argument("--journal", default="state/aimos.sqlite",
                    help="path to the single-user journal to migrate")
    args = ap.parse_args(argv)

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    # get_engine() runs Alembic migrations and seeds the admin user.
    get_engine()
    session = get_session_maker()()

    user: User | None = None
    if args.admin_email and args.admin_password:
        user = session.query(User).filter(User.email == args.admin_email).first()
        if user is None:
            user = User(
                email=args.admin_email,
                password_hash=hash_password(args.admin_password),
                email_verified=True,
                phone_verified=False,
            )
            session.add(user)
            session.flush()

    owner_id = user.id if user else None
    org = session.get(Organization, args.org_id)
    if org is None:
        org = Organization(
            id=args.org_id,
            name=args.org_name,
            slug=args.org_slug,
            owner_id=owner_id,
            mode="paper",
        )
        session.add(org)
        session.flush()
    elif owner_id and org.owner_id is None:
        org.owner_id = owner_id
        session.flush()

    config = session.get(OrganizationConfig, args.org_id)
    if config is None:
        config = OrganizationConfig(organization_id=args.org_id, overrides={})
        session.add(config)

    if user:
        existing = session.query(OrganizationMember).filter(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == args.org_id,
        ).first()
        if existing is None:
            session.add(OrganizationMember(
                organization_id=args.org_id,
                user_id=user.id,
                role="owner",
            ))

    session.commit()
    session.close()

    # Migrate existing single-user journal to per-tenant path if present.
    old_journal = Path(args.journal)
    journal_dir = state_dir / "journals"
    new_journal = journal_dir / f"{args.org_id}.sqlite"
    if old_journal.exists() and not new_journal.exists():
        journal_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_journal, new_journal)
        print(f"copied journal: {old_journal} -> {new_journal}")

    print("\nMigration complete. Set these before starting the SaaS server:")
    print(f"  AIMOS__FEATURES__SAAS_ENABLED=true")
    print(f"  AIMOS_RUNTIME_ORG_ID={args.org_id}")
    print(f"  AIMOS__PAPER__JOURNAL_PATH={new_journal}")
    if user:
        print(f"\nOwner user created: {args.admin_email}")
    print("\nThen run: python -m aimos.runtime.serve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
