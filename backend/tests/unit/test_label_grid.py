"""Snippets below are transcribed from the six client documents in
``client-formats/*/[A-Z]*_transcription.md``.  Grid rows use the three-space
column join that ``docx_ingest._table_row_text`` emits for Word tables.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.extraction.label_grid import (
    FIELD_SYNONYMS,
    parse_date,
    parse_money,
    read_label_values,
)

FORMAT_1_ASSESSMENT = """Assessment report
Assessment Number   L0987892222   Version
Report type   Full report   Printed   03/02/2023
Summary Information
Assessment Number   D7576879   Reference Name   John Doe
First Received   12/11/2025   Assigned to   DL
Assessment Status   Active   Auth/total loss date
Authorization Status   Authorized   Date of accident   30/12/2025
Work Provider   DL- Marvin   Excess   £0.00
Claim Reference   245338996/1   Able to authorize repairs   Yes
Policy Number   PH   Are the repairs authorized   Yes
Version   fhfjdd1/2   VAT Status   Non Taxable
Vehicle Details
Manufacturer: HYUNDAI
Model: 140 SE Nav
Model Sheet Number: 3071
Registration Number: AB12XYZ
VIN Number: ABCD1234567
Odometer: 576882 miles
Calculation
Labour Rate   £38.00
Paint Rate   £68.00
Total Labour   £2509.20
Total Paint / Materials Costs   1029.57
Total Parts   1237.50
Total Additional Costs   136.32
Repair Grand Total Excl. VAT   4912.59
Grand Total Excl. VAT   4912.59
VAT 20%   982.52
Grand Total Incl. VAT   5895.11
Total Due   5895.11
Assessment Number   D38892222   Version   fhfjdd1/2   Full report   Printed   26/11/2026
"""

FORMAT_2_INVOICE = """DL Assistance
** Request for Payment **
Invoice Date   26/11/2025
Invoice Number   22564547648/1~AJ123456
Reference Name   John Doe   Vehicle Registration   A30DRY
Claim No   123456/1   Vehicle Make   SKODA
Policy No   103466899   Vehicle Model   KAROQ SE TSI 115]
Assessment Ref   BOY1537   Excess   £0.00
Collection Date   Insured VAT Status   Non Taxable
Item Description   Cost   Sum Equivalent to VAT @20%
Total Parts Amount   448.91   89.78
Total Paint & Materials Amount   1034.02   206.80
Total Labour Amount   2008.00   401.60
Total   3490.93   698.18
Additional charges   627.00   125.40
Deductions   0.00   0.00
Invoice Total   4941.52
Policy Excess Paid by Customer-   0.00
Total Due   4941.52
"""

FORMAT_7_ASSESSMENT_TOTALS = """Total Paint / Materials Costs   785.00
Total Parts   939.00
Total Additional Costs   104.00
Repair Grand Total Excl. VAT   3738.00
Grand Total Excl. VAT   3738.00
VAT 20%   747.60
Grand Total Incl. VAT   4485.60
"""

FORMAT_7_INVOICE_TOTALS = """Total Labour   1910.00
Total Paint & materials   785.00
An amount equivalent to VAT @20%   747.60
Total Due   4485.60
"""

FORMAT_1_INVOICE_HEADER = """DLAS
INVOICE
Invoice Date: 2/3/2023
Invoice Number: 343653726836/1~3538
DL Claim number: 245338996/1
DL policyholder: John Doe
Vehicle Registration : AB12XYZ
"""


def test_format_1_assessment_identity_prefers_the_summary_grid() -> None:
    values = read_label_values(FORMAT_1_ASSESSMENT)

    assert values["claim_reference"] == "245338996/1"
    assert values["policy_number"] == "PH"
    assert values["registration"] == "AB12XYZ"
    assert values["vehicle_make"] == "HYUNDAI"
    assert values["vehicle_model"] == "140 SE Nav"
    assert values["vin"] == "ABCD1234567"
    assert values["customer_name"] == "John Doe"
    assert values["authorisation_status"] == "Authorized"
    assert values["incident_date"] == "30/12/2025"
    assert values["mileage"] == "576882 miles"
    # The page-1 header band prints L0987892222 and later running headers
    # print D38892222; the Summary Information grid wins over both.
    assert values["assessment_number"] == "D7576879"


def test_format_1_assessment_money_labels() -> None:
    values = read_label_values(FORMAT_1_ASSESSMENT)

    assert values["labour_rate"] == "£38.00"
    assert parse_money(values["labour_rate"]) == Decimal("38.00")
    assert parse_money(values["paint_rate"]) == Decimal("68.00")
    assert parse_money(values["labour_net"]) == Decimal("2509.20")
    assert parse_money(values["paint_net"]) == Decimal("1029.57")
    assert parse_money(values["parts_net"]) == Decimal("1237.50")
    assert parse_money(values["extras_net"]) == Decimal("136.32")
    assert parse_money(values["subtotal_net"]) == Decimal("4912.59")
    # "VAT Status   Non Taxable" appears first but only as a loose prefix
    # match; the strict "VAT 20%" cell wins.
    assert parse_money(values["vat_total"]) == Decimal("982.52")
    assert parse_money(values["gross_total"]) == Decimal("5895.11")


def test_format_2_invoice_reference_grid() -> None:
    values = read_label_values(FORMAT_2_INVOICE)

    assert values["claim_reference"] == "123456/1"
    assert values["policy_number"] == "103466899"
    assert values["registration"] == "A30DRY"
    assert values["vehicle_make"] == "SKODA"
    assert values["vehicle_model"] == "KAROQ SE TSI 115]"
    assert values["assessment_number"] == "BOY1537"
    assert values["invoice_number"] == "22564547648/1~AJ123456"
    assert values["customer_name"] == "John Doe"
    assert parse_date(values["invoice_date"]) == date(2025, 11, 26)


def test_format_2_invoice_rolled_up_totals() -> None:
    values = read_label_values(FORMAT_2_INVOICE)

    assert parse_money(values["labour_net"]) == Decimal("2008.00")
    assert parse_money(values["paint_net"]) == Decimal("1034.02")
    assert parse_money(values["extras_net"]) == Decimal("627.00")
    # The bare "Total" line is deliberately not a subtotal synonym: it heads
    # every schedule on these documents, so the parsers own section totals.
    assert parse_money(values["parts_net"]) == Decimal("448.91")
    assert "subtotal_net" not in values
    assert parse_money(values["gross_total"]) == Decimal("4941.52")


def test_longer_label_wins_over_shorter_prefix_without_column_spacing() -> None:
    values = read_label_values("Total 136.32\nSubtotal 3490.93\nTotal Parts Amount 448.91\n")

    assert parse_money(values["subtotal_net"]) == Decimal("3490.93")
    assert parse_money(values["parts_net"]) == Decimal("448.91")
    assert not any(value == "136.32" for value in values.values())


def test_format_7_gross_total_from_either_label() -> None:
    assert parse_money(read_label_values(FORMAT_7_ASSESSMENT_TOTALS)["gross_total"]) == Decimal(
        "4485.60"
    )
    invoice = read_label_values(FORMAT_7_INVOICE_TOTALS)
    assert parse_money(invoice["gross_total"]) == Decimal("4485.60")
    assert parse_money(invoice["labour_net"]) == Decimal("1910.00")
    assert parse_money(invoice["paint_net"]) == Decimal("785.00")
    assert parse_money(invoice["vat_total"]) == Decimal("747.60")


def test_format_1_invoice_header_keeps_raw_values() -> None:
    values = read_label_values(FORMAT_1_INVOICE_HEADER)

    assert values["invoice_number"] == "343653726836/1~3538"
    assert values["claim_reference"] == "245338996/1"
    assert values["customer_name"] == "John Doe"
    assert values["registration"] == "AB12XYZ"
    assert parse_date(values["invoice_date"]) == date(2023, 3, 2)


def test_label_on_one_line_value_on_the_next() -> None:
    values = read_label_values(
        "Registration Number\nAB12XYZ\nManufacturer\nHYUNDAI\nGrand Total Incl. VAT\n5895.11\n"
    )

    assert values["registration"] == "AB12XYZ"
    assert values["vehicle_make"] == "HYUNDAI"
    assert parse_money(values["gross_total"]) == Decimal("5895.11")


def test_blank_values_yield_no_key() -> None:
    values = read_label_values("Claim No   123456/1   Policy No\nItem Description   Cost\n")

    assert values["claim_reference"] == "123456/1"
    assert "policy_number" not in values
    # "Sum Equivalent to VAT @20%" is a column heading with no amount beside it.
    assert "vat_total" not in read_label_values(
        "Item Description   Cost   Sum Equivalent to VAT @20%\nTotal Parts Amount   448.91   89.78\n"
    )


def test_read_label_values_tolerates_empty_input() -> None:
    assert read_label_values("") == {}


def test_money_and_date_helpers() -> None:
    assert parse_money("£1,237.50") == Decimal("1237.50")
    assert parse_money("2509.20") == Decimal("2509.20")
    assert parse_money("") is None
    assert parse_money("Non Taxable") is None
    assert parse_date("30/12/2025") == date(2025, 12, 30)
    assert parse_date("2/3/2023") == date(2023, 3, 2)
    assert parse_date("31/02/2025") is None
    assert parse_date("not a date") is None


def test_field_synonyms_cover_every_documented_field() -> None:
    expected = {
        "claim_reference",
        "policy_number",
        "registration",
        "assessment_number",
        "vehicle_make",
        "vehicle_model",
        "vin",
        "invoice_number",
        "invoice_date",
        "incident_date",
        "authorisation_status",
        "customer_name",
        "mileage",
        "labour_rate",
        "paint_rate",
        "labour_net",
        "paint_net",
        "parts_net",
        "extras_net",
        "subtotal_net",
        "vat_total",
        "gross_total",
    }

    assert expected <= set(FIELD_SYNONYMS)
