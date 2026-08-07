"""Idempotent database bootstrap for local SQLite deployments."""

from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.db_types import utc_now
from app.enums import (
    ApprovalStatus,
    ConfigKind,
    ConfigStatus,
    OntologyVersionStatus,
)
from app.models import ConfigVersion, OntologyVersion, RegulatoryRule
from app.services.vehicle_category_lookup import seed_vehicle_category_lookup

DEFAULT_POLICY_VERSION = "claimguard-policy-v1.4"
DEFAULT_POLICY_YAML = """\
policy:
  version: claimguard-policy-v1.4
  currency: GBP
  jurisdiction: UK
benchmark:
  ontology_weight: 0.60
  historical_weight: 0.40
  minimum_historical_sample: 3
  historical_half_life_months: 12
  stale_after_months: 24
challenge:
  basis: net_line_total
  sum_positive_only: true
  amber:
    minimum_amount_gbp: \"5.00\"
    minimum_percentage: 5
  red:
    minimum_amount_gbp: \"25.00\"
    minimum_percentage: 25
letters:
  figures: net
  show_separate_vat_impact: true
  mot_outside_vat: true
liability_gate:
  human_confirmation_required: true
  invoice_can_determine_fault: false
"""

DEFAULT_FEATURE_VERSION = "claimguard-features-v1.4"
DEFAULT_FEATURE_YAML = """\
features:
  two_step_approval: false
  auto_research: false
  reviewer_initiated_research: true
  invoice_level_settlement_required: true
  line_level_settlement_optional: true
"""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _install_sqlite_audit_triggers(target_engine: Engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return
    statements = (
        """
        CREATE TRIGGER IF NOT EXISTS audit_events_no_update
        BEFORE UPDATE ON audit_events
        BEGIN
            SELECT RAISE(ABORT, 'audit_events are append-only');
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
        BEFORE DELETE ON audit_events
        BEGIN
            SELECT RAISE(ABORT, 'audit_events are append-only');
        END
        """,
    )
    with target_engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


def _seed_config(session: Session) -> None:
    policy = session.scalar(
        select(ConfigVersion).where(
            ConfigVersion.kind == ConfigKind.POLICY,
            ConfigVersion.version == DEFAULT_POLICY_VERSION,
        )
    )
    if policy is None:
        policy = ConfigVersion(
            kind=ConfigKind.POLICY,
            version=DEFAULT_POLICY_VERSION,
            yaml_text=DEFAULT_POLICY_YAML,
            config_hash=_sha256_text(DEFAULT_POLICY_YAML),
            status=ConfigStatus.ACTIVE,
            created_by="system-bootstrap",
            activated_at=utc_now(),
            change_summary="Build-ready ClaimGuard v1.4 pilot defaults.",
        )
        session.add(policy)

    features = session.scalar(
        select(ConfigVersion).where(
            ConfigVersion.kind == ConfigKind.FEATURE_FLAGS,
            ConfigVersion.version == DEFAULT_FEATURE_VERSION,
        )
    )
    if features is None:
        features = ConfigVersion(
            kind=ConfigKind.FEATURE_FLAGS,
            version=DEFAULT_FEATURE_VERSION,
            yaml_text=DEFAULT_FEATURE_YAML,
            config_hash=_sha256_text(DEFAULT_FEATURE_YAML),
            status=ConfigStatus.ACTIVE,
            created_by="system-bootstrap",
            activated_at=utc_now(),
            change_summary="Pilot feature decisions from the v1.4 decision log.",
        )
        session.add(features)


def _seed_ontology_version(session: Session) -> None:
    existing = session.scalar(select(OntologyVersion).where(OntologyVersion.sequence_number == 0))
    if existing is None:
        session.add(
            OntologyVersion(
                sequence_number=0,
                label="ontology-v0-bootstrap",
                status=OntologyVersionStatus.PUBLISHED,
                created_by="system-bootstrap",
                change_summary="Empty bootstrap version before seed workbook import.",
                published_at=utc_now(),
            )
        )


def _seed_regulatory_rules(session: Session) -> None:
    vat_rule = session.scalar(
        select(RegulatoryRule).where(
            RegulatoryRule.rule_name == "UK_STANDARD_VAT_RATE",
            RegulatoryRule.jurisdiction == "UK",
            RegulatoryRule.effective_from == date(2011, 1, 4),
        )
    )
    if vat_rule is None:
        session.add(
            RegulatoryRule(
                rule_name="UK_STANDARD_VAT_RATE",
                jurisdiction="UK",
                effective_from=date(2011, 1, 4),
                value="20.0000",
                value_type="percentage",
                source_reference="ClaimGuard PRD pilot baseline; verify against HMRC before production use.",
                approval_status=ApprovalStatus.APPROVED,
            )
        )

    mot_rule = session.scalar(
        select(RegulatoryRule).where(
            RegulatoryRule.rule_name == "UK_CAR_MOT_MAX_FEE",
            RegulatoryRule.jurisdiction == "UK",
            RegulatoryRule.effective_from == date(2025, 1, 1),
        )
    )
    if mot_rule is None:
        session.add(
            RegulatoryRule(
                rule_name="UK_CAR_MOT_MAX_FEE",
                jurisdiction="UK",
                effective_from=date(2025, 1, 1),
                value="54.85",
                value_type="GBP_VAT_EXEMPT",
                source_reference="ClaimGuard PRD pilot baseline; verify against GOV.UK before production use.",
                approval_status=ApprovalStatus.APPROVED,
            )
        )


def initialize_database(
    target_engine: Engine = engine,
    *,
    seed_defaults: bool = True,
) -> None:
    """Create the schema, immutable-audit triggers, and idempotent pilot defaults."""

    Base.metadata.create_all(bind=target_engine)
    _install_sqlite_audit_triggers(target_engine)
    if not seed_defaults:
        return

    session_factory = SessionLocal
    if target_engine is not engine:
        from sqlalchemy.orm import sessionmaker

        session_factory = sessionmaker(
            bind=target_engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )

    with session_factory.begin() as session:
        _seed_config(session)
        _seed_ontology_version(session)
        _seed_regulatory_rules(session)
        seed_vehicle_category_lookup(session)


if __name__ == "__main__":
    initialize_database()
