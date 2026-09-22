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


# The Vehicle Details grid of every client assessment is printed beside the
# free-text Model Options list. A renderer that collapses the gap between the
# two columns to a single space hands the reader one run-on cell per row -- the
# shape that made the running app store "AB12XYZ WITH A/C" and
# "140 SE Nav FROM 06/2017" for format 1.
FORMAT_1_VEHICLE_DETAILS_COLUMNS_COLLAPSED = """Vehicle Details
Manufacturer: HYUNDAI Model Options
Model: 140 SE Nav FROM 06/2017
Model Sheet Number: 3071 MODEL i30
Engine: 1.7 LTR 85 KW HEAT ABSORBING GLASS
Registration Number: AB12XYZ WITH A/C
VIN Number: ABCD1234567 DRIVER SEAT HEIGHT
Odometer: 576882 miles WITHOUT ALARM
"""

FORMAT_2_SUMMARY_COLUMNS_COLLAPSED = """Summary Information
Assessment Number D7576879 Reference Name John Doe
Claim Reference 123456/1 Able to authorize repairs Yes
Policy Number 103466899 Are the repairs authorized Yes
"""


def test_a_run_on_cell_value_ends_at_the_printed_value() -> None:
    values = read_label_values(FORMAT_1_VEHICLE_DETAILS_COLUMNS_COLLAPSED)

    assert values["registration"] == "AB12XYZ"
    assert values["vin"] == "ABCD1234567"


def test_a_run_on_grid_row_keeps_its_own_value_not_the_next_pair() -> None:
    values = read_label_values(FORMAT_2_SUMMARY_COLUMNS_COLLAPSED)

    assert values["assessment_number"] == "D7576879"
    assert values["claim_reference"] == "123456/1"
    assert values["policy_number"] == "103466899"


def test_a_value_with_no_declared_shape_is_never_truncated() -> None:
    """Make, model and mileage have no single-token shape, so they keep it all.

    Cutting them would be a guess, and a guess costs "140 SE Nav" its last two
    words. The documented consequence is that a collapsed render leaves a
    visible tail on those fields rather than a silently shortened value.
    """

    values = read_label_values(
        "Model   140 SE Nav\nManufacturer   HYUNDAI\nOdometer   576882 miles\n"
    )

    assert values["vehicle_model"] == "140 SE Nav"
    assert values["vehicle_make"] == "HYUNDAI"
    assert values["mileage"] == "576882 miles"


def test_a_neighbouring_cell_is_a_value_boundary_and_is_never_trimmed() -> None:
    """Only a run-on cell is cut; a printed cell means all of what it prints."""

    values = read_label_values("Policy No   AB 12 34   Vehicle Make   SKODA\n")

    assert values["policy_number"] == "AB 12 34"


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


# --------------------------------------------------------------------------
# Value boundaries.  Every case below is printed by a document in
# ``client-formats/`` or documented in ``app/domain/normalisation.py``.
# --------------------------------------------------------------------------


def test_an_identifier_printed_with_spaces_around_its_slash_is_kept_whole() -> None:
    """``normalisation.normalise_identifier`` exists to absorb this spacing.

    Cutting the value before it runs is what made an assessment's
    ``245338996 / 1`` conflict with its invoice's ``245338996/1`` and refuse a
    correct pair -- the failure this reader is supposed to prevent.
    """

    values = read_label_values("Policy Number: AB 12 34\nClaim Reference: 245338996 / 1\n")

    assert values["claim_reference"] == "245338996 / 1"
    assert values["policy_number"] == "AB 12 34"


def test_two_claims_on_one_policy_never_collapse_into_the_same_value() -> None:
    """``123456/1`` and ``123456/2`` are two claims, not one printed twice.

    A shared truncation compares equal, so it does not merely lose a pair --
    it manufactures one, at full confidence, on a key neither document
    printed that way.
    """

    first = read_label_values("Claim Reference: 245338996 / 1\n")
    second = read_label_values("Claim Reference: 245338996 / 2\n")

    assert first["claim_reference"] != second["claim_reference"]


def test_a_shaped_field_never_reports_a_bare_english_word() -> None:
    """Format 1's Summary grid prints ``Policy Number`` with no value at all.

    Collapsed, the row reads ``Policy Number Are the repairs authorized Yes``.
    Reporting ``Are`` from it would survive normalisation and match every
    other format-1 assessment whose policy number is equally blank.
    """

    assert "policy_number" not in read_label_values(
        "Policy Number Are the repairs authorized Yes\n"
    )


def test_a_registration_run_on_is_cut_only_where_free_text_follows() -> None:
    """``ABC1234`` is the plate in ``sample-data/auda-style/Auda7_full_report.pdf``."""

    assert read_label_values("Registration Number: ABC1234 WITH A/C\n")["registration"] == (
        "ABC1234"
    )
    assert read_label_values("Registration Number: AB12XYZ WITH A/C\n")["registration"] == (
        "AB12XYZ"
    )


def test_a_printed_registration_is_never_shortened() -> None:
    """Plates are printed with spaces, and not every one is ``AB12XYZ``."""

    printed = ["GAZ 1234", "1 ABC", "JB 007", "MH12AB1234", "AB12 XYZ", "AM06TAH"]

    for value in printed:
        assert read_label_values(f"Registration Number: {value}\n")["registration"] == value


def test_a_vin_split_by_a_space_is_not_cut_to_a_shared_prefix() -> None:
    """An eight-character VIN prefix is shared by every car of that model.

    ``DRIVER SEAT HEIGHT`` is a Model Options item and is evidence of a lost
    column break; ``BR12345`` could be the rest of the VIN and is not.
    """

    assert read_label_values("VIN Number: WF0AXXWPMA BR12345\n")["vin"] == "WF0AXXWPMA BR12345"
    assert read_label_values("VIN Number: ABCD1234567 DRIVER SEAT HEIGHT\n")["vin"] == (
        "ABCD1234567"
    )


def test_a_neighbouring_label_value_cell_is_not_this_fields_value() -> None:
    """One grid row, two label/value pairs, and the left value is blank.

    This line is printed by every DL Auda Summary grid in the corpus.
    """

    values = read_label_values("Policy Number:                       VAT Status: Non Taxable\n")

    assert "policy_number" not in values
    assert "vat_total" not in values


def test_a_blank_label_does_not_swallow_the_next_lines_label_value_pair() -> None:
    """Format 1 prints blank values, so the next line is often another label."""

    values = read_label_values("Registration Number:   \nVIN Number: ABCD1234567\n")

    assert "registration" not in values
    assert values["vin"] == "ABCD1234567"


def test_the_model_options_heading_is_neither_a_model_nor_a_value() -> None:
    """Every DL Auda report prints ``Model Options`` beside Vehicle Details.

    Format 4 prints a blank ``Model Sheet Number`` directly above it, and both
    headings open with the ``Model`` synonym, so both are read as a model and
    both are offered as the value of whatever label printed a blank.
    """

    values = read_label_values(
        "Manufacturer: FORD\nModel: Puma\nModel Sheet Number:   \nOdometer:   \nModel Options\n"
    )

    assert values["vehicle_model"] == "Puma"
    assert "mileage" not in values

    headings_only = read_label_values(
        "Model Sheet Number:   \nModel Options\nRegistration Number: PD73UUF\n"
    )

    assert "vehicle_model" not in headings_only
    assert headings_only["registration"] == "PD73UUF"


def test_a_longer_label_is_not_left_on_the_front_of_its_value() -> None:
    """The EXL invoice prints ``Insured Name   John Smith``.

    Its renderer collapses the column gap, so the reader is handed one
    run-on cell and takes the longest label it knows off the front.  With
    only the bare ``Insured`` in the table that is one word short and the
    customer's name comes back as "Name John Smith".
    """

    assert read_label_values("Insured Name   John Smith\n")["customer_name"] == "John Smith"
    assert read_label_values("Insured Name John Smith\n")["customer_name"] == "John Smith"
    # The bare synonym still reads the shape the DLAS grids print.
    assert read_label_values("Insured   John Smith\n")["customer_name"] == "John Smith"


def test_explicit_claim_label_preserves_prefix_and_does_not_read_heading():
    assert read_label_values("Claim: ABC 123456")["claim_reference"] == "ABC 123456"
    assert "claim_reference" not in read_label_values("Claim\nSummary Information\nAssessment Number   D123")
