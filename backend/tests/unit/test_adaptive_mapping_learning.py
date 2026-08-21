from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.enums import (
    ApprovalStatus,
    ConfidenceLevel,
    LineItemKind,
    OntologyItemStatus,
    PriceVatBasis,
)
from app.init_db import initialize_database
from app.models import OntologyItem, OntologySynonym, OntologyVersion
from app.services.mapping_review import _learn_approved_synonym


def test_handler_approved_description_becomes_reusable_synonym() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialize_database(engine)

    with Session(engine) as session:
        version = session.scalar(select(OntologyVersion))
        assert version is not None
        item = OntologyItem(
            canonical_code="TEST-DOOR-SEAL",
            canonical_name="Lower door seal",
            item_type=LineItemKind.PART,
            category="Body",
            unit="each",
            region="UK",
            price_vat_basis=PriceVatBasis.NET,
            currency="GBP",
            status=OntologyItemStatus.APPROVED,
            approval_status=ApprovalStatus.APPROVED,
            confidence_level=ConfidenceLevel.HIGH,
            created_by="pytest",
            created_in_version_id=version.id,
        )
        session.add(item)
        session.flush()

        synonym_id = _learn_approved_synonym(
            session,
            line=SimpleNamespace(id="line-7", raw_description="LWR door seal"),
            item=item,
            version=version,
        )

        learned = session.get(OntologySynonym, synonym_id)
        assert learned is not None
        assert learned.normalised_synonym == "lwr door seal"
        assert learned.approval_status == ApprovalStatus.APPROVED
        assert learned.source_reference == "invoice_line:line-7"

        other_item = OntologyItem(
            canonical_code="TEST-OTHER-SEAL",
            canonical_name="Other seal",
            item_type=LineItemKind.PART,
            category="Body",
            unit="each",
            region="UK",
            price_vat_basis=PriceVatBasis.NET,
            currency="GBP",
            status=OntologyItemStatus.APPROVED,
            approval_status=ApprovalStatus.APPROVED,
            confidence_level=ConfidenceLevel.HIGH,
            created_by="pytest",
            created_in_version_id=version.id,
        )
        session.add(other_item)
        session.flush()
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(
                OntologySynonym(
                    ontology_item_id=other_item.id,
                    synonym="LWR door seal",
                    normalised_synonym="lwr door seal",
                    source_type="handler_approved_invoice_mapping",
                    source_reference="invoice_line:line-8",
                    approval_status=ApprovalStatus.APPROVED,
                    created_in_version_id=version.id,
                )
            )
            session.flush()

    engine.dispose()
