"""Build the six client-format `.docx` fixtures used by the invoice <-> assessment
matching work (see `.claude/team-runs/invoice-assessment-matching-plan.md`, Task 2).

These files replicate -- as faithfully as `python-docx` allows -- the three
DL Auda/DLAS claim pairs transcribed from the client's phone photos:

    client-formats/2026-09-15_dl-auda-format-1-assessment-report/
    client-formats/2026-09-15_dl-auda-format-2-engineer-report-2/
    client-formats/2026-09-15_dl-auda-format-7-engineer-report/

Every value below is taken verbatim from the corresponding `*_transcription.md`
file, including the documents' own internal flaws (mismatched totals,
duplicate invoice numbers, conflicting assessment numbers, an embedded
"Validation note" paragraph, etc.) -- those flaws are the point: they are what
the extraction and pairing logic must be tested against. No real client file
is read, written, or committed by this script; there are none in this repo.

Usage (from backend/):

    uv run python scripts/build_client_format_fixtures.py

Writes 6 `.docx` files plus `manifest.json` into `sample-data/client-formats/`
at the repo root (a sibling of `sample-data/auda-style/`), which this script
does not touch. Idempotent: re-running overwrites the same files.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from docx.document import Document as DocxDocumentType
from docx.enum.text import WD_BREAK
from docx.table import Table as DocxTable

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "sample-data" / "client-formats"

DLAS_ISSUER_BLOCK = (
    "DL Insurance Limited, Central Invoicing Dept, St Clare House, "
    "30-33 Minories, London, EC3N 1DD"
)
REPAIRER_FOOTER = (
    "DL Assistance Accident repair Center Ltd, Registered in England & Wales "
    "No 1234, registered Office: St Clare House, 30-33 Minories, London, EC3N 1DD"
)
INVOICE_TERMS = "This invoice is due for payment within 30 days"


# --------------------------------------------------------------------------
# Small document-building helpers. Table rows are what `docx_ingest.py`'s
# `_table_row_text` reads back as 2+-space-joined columns, so every grid the
# transcriptions describe as a table is built here as a real `python-docx`
# table (not paragraphs formatted to merely look like one).
# --------------------------------------------------------------------------


def _new_document() -> DocxDocumentType:
    return DocxDocument()


def add_heading_line(doc: DocxDocumentType, text: str, *, bold: bool = True) -> None:
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(text)
    run.bold = bold


def add_paragraphs(doc: DocxDocumentType, lines: list[str]) -> None:
    for line in lines:
        doc.add_paragraph(line)


def add_grid_table(doc: DocxDocumentType, rows: list[tuple[str, str, str, str]]) -> DocxTable:
    """Two-column label/value grid (label, value, label, value), no colons."""

    table = doc.add_table(rows=0, cols=4)
    table.style = "Table Grid"
    for label_a, value_a, label_b, value_b in rows:
        cells = table.add_row().cells
        cells[0].text = label_a
        cells[1].text = value_a
        cells[2].text = label_b
        cells[3].text = value_b
    return table


def add_label_grid(doc: DocxDocumentType, rows: list[tuple[str, str]]) -> DocxTable:
    """Single-column label/value grid (label, value), no colons.

    The DLAS "INVOICE" header and the "Request for Payment" invoice-date block
    print their identity fields exactly like this -- a label cell beside a
    value cell, with no colon anywhere on the document. Building them as a real
    table (rather than the "Label: value" paragraphs this script used to emit)
    is what makes the fixtures reproduce the client's own layout.
    """

    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value
    return table


def add_schedule_table(
    doc: DocxDocumentType, header: list[str], rows: list[list[str]]
) -> DocxTable:
    table = doc.add_table(rows=0, cols=len(header))
    table.style = "Table Grid"
    header_cells = table.add_row().cells
    for idx, text in enumerate(header):
        header_cells[idx].text = text
    for row in rows:
        cells = table.add_row().cells
        for idx, text in enumerate(row):
            cells[idx].text = text
    return table


def add_page_break(doc: DocxDocumentType) -> None:
    paragraph = doc.add_paragraph()
    paragraph.add_run().add_break(WD_BREAK.PAGE)


# --------------------------------------------------------------------------
# Format 1 -- assessment report
# --------------------------------------------------------------------------


def build_auda_format_1_assessment() -> DocxDocumentType:
    doc = _new_document()

    # Page-1 header block. The page header's own assessment number
    # (L0987892222) deliberately disagrees with the Summary Information
    # grid below (D7576879) -- this is the client's own inconsistency.
    add_heading_line(doc, "Assessment report")
    add_paragraphs(
        doc,
        [
            "Assessment Number: L0987892222",
            "Version:",
            "Full report",
            "Printed: 03/02/2023",
        ],
    )

    add_heading_line(doc, "Summary Information")
    doc.add_paragraph("Claim")
    add_grid_table(
        doc,
        [
            ("Assessment Number", "D7576879", "Reference Name", "John Doe"),
            ("First Received", "12/11/2025", "Assigned to", "DL"),
            ("Assessment Status", "Active", "Auth/total loss date", ""),
            ("Authorization Status", "Authorized", "Date of accident", "30/12/2025"),
            ("Work Provider", "DL- Marvin", "Excess", "£0.00"),
            ("Claim Reference", "245338996/1", "Able to authorize repairs", "Yes"),
            ("Policy Number", "PH", "Are the repairs authorized", "Yes"),
            ("Other reference", "", "Date of inspection", ""),
            ("Version", "fhfjdd1\\/2", "Place of inspection", "Repairer"),
            ("Decision date", "25/11/2025", "VAT Status", "Non Taxable"),
        ],
    )

    add_heading_line(doc, "Vehicle Details")
    add_paragraphs(
        doc,
        [
            "Manufacturer: HYUNDAI",
            "Model: 140 SE Nav",
            "Model Sheet Number: 3071",
            "Engine: 1.7 LTR 85 KW",
            "Registration Number: AB12XYZ",
            "VIN Number: ABCD1234567",
            "Registration Month: march",
            "Registration Year: 2018",
            "Odometer: 576882 miles",
        ],
    )

    add_heading_line(doc, "Model Options")
    model_options = (
        "FROM 06/2017 · MODEL i30 · HEAT ABSORBING GLASS · WITH A/C · "
        "DRIVER SEAT HEIGHT · WITHOUT ALARM · ELECTRIC FOLDING MIRROR · "
        "HEATED WINDSCREEN · FRONT / REAR PARKING SENSOR · REAR CAMERA · "
        "STEERING WHEEL CONTROLS · START / STOP SYSTEM · CRUISE CONTROL · "
        "DOOR COVERS · TIRE REPAIR KIT · DIMENSION 570 R/O · BASECOAT CLEAR"
    )
    add_paragraphs(doc, [item.strip() for item in model_options.split("·")])

    add_heading_line(doc, "Vehicle Condition")
    add_paragraphs(
        doc,
        [
            "Tyres: Good",
            "Pre accident: Good",
            "Steering: Satisfactory",
            "Brakes: Satisfactory",
            "Severity of impact:",
            "Damage Areas:",
            "Tyres- Depth (MM): Front Left Hand Inner: 4mm · Front Right Hand "
            "Inner: 4mm · Rear Left hand Inner: 4mm · Rear Right Hand Innder: 4mm",
            "Addresses — Insured: John Doe",
            'Note: "Using Manufacturer Times"',
        ],
    )

    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Assessment Number: D38892222",
            "Version: fhfjdd1\\/2",
            "Full report",
            "Printed: 26/11/2026",
        ],
    )

    add_heading_line(doc, "Repair Information")
    add_heading_line(doc, "LABOUR")
    doc.add_paragraph("Time Basis 10 WU=1HR.")
    labour_rows = [
        ["52803000", "A30 - R/R OUTER VEHICLE C/R", "10"],
        ["87751000", "R + R SILL COVER, LH", "2"],
        ["87751000", "R + R SILL COVER", "2"],
        ["82510R00", "R + R LEFT FRONT OUTER WINDOW CHANNEL", "2"],
        ["82650R00", "R + R LEFT FRONT OUTER DOOR HANDLE", "2"],
        ["87610R00", "R + R DOOR MIRROR", "2"],
        ["87320R00", "R + R LEFT WEATHERSTRIP", "2"],
        ["", "REMOVE ATTACHED PARTS", "4"],
        ["NO NUMBER", "BODY WORK FOR LEFT FRONT DOOR", "4"],
        ["82300R00", "R + R UPPER WEATHER STRIP", "2"],
        ["82410R00", "R + R OUTER SEAL AND LAP", "2"],
        ["82520R00", "R + R LEFT FRONT INNER GLASS", "2"],
        ["82610R00", "R + R LEFT REAR INNER / DOOR SHELL", "2"],
        ["", "R + R BELT MOULDING", "2"],
        ["", "R + R SIDE MOULDING", "3"],
        ["", "REMOVE / REFIT DOOR TRIM", "3"],
        ["", "DISCONNECT / RECONNECT VEHICLE BATTERY", "1"],
        ["", "REPROGRAM / REINITIALISE VEHICLE SYSTEMS", "1"],
        ["1000", "R + R / REFIT FRONT DOOR INTERNALS", "5"],
        ["1000", "REMOVE / REFIT DOOR PANELS", "5"],
        ["1000", "REPAIR LEFT REAR / QUARTER PANEL", "13"],
        ["1000", "REPAIR LEFT SILL / BODY AREA", "15"],
        ["1000", "PULL / ALIGN REPAIR SYSTEM", "5"],
        ["1000", "SET UP MIRACLE PULL SYSTEM", "5"],
        ["1000", "CORROSION PROTECTION / 2 SIDES", "5"],
        # Rows sum to 101 WU; the printed total below is 218 -- the source
        # document's own flaw, reproduced verbatim (never reconciled).
        ["", "Total Work Units", "218"],
    ]
    add_schedule_table(doc, ["Number", "Description", "WU"], labour_rows)

    add_heading_line(doc, "PAINT WORK")
    paint_rows = [
        ["1781", "L/R DOOR NEW PART PAINTING", "15"],
        ["2185", "L/SILL PANEL COVER NEW PART FRONT K2", "7"],
        ["2185", "OUTER SILL PANEL REPAIR PAINTING", "10"],
        ["3465", "L/R OUTER QUARTER PANEL REPAIR PAINTING", "24"],
        ["1521", "L/R INNER PANEL PAINTING", "26"],
        ["1521", "L/R LOWER DOOR SURFACE PAINT", "8"],
        ["2279", "LEFT B-PILLAR / SURFACE PAINT", "4"],
        ["4390", "L/R ROOF SECTION SURFACE PAINT", "5"],
        ["", "FUEL FILLER FLAP SURFACE PAINT", "3"],
        ["1000", "REAR WING / PANEL BEFORE PAINTING", "5"],
        ["1000", "FINAL COLOUR MATCH", "2"],
        ["1000", "ALL FADE OUT POLISH", "5"],
        ["1000", "L/R SIDE GLASS MASK", "3"],
        ["1000", "SEAM SEAL AS REQUIRED PAINTING", "3"],
        ["1000", "TRIM / BODY REPAIR PAINTING", "3"],
        ["", "PREPARATION FOR PRE-PAINTING", "28"],
        ["", "Total Work Units", "151.0"],
    ]
    add_schedule_table(doc, ["Number", "Description", "WU"], paint_rows)

    add_heading_line(doc, "PARTS")
    parts_rows = [
        ["1781", "L/R DOOR", "7700332300", "0%", "847.73"],
        ["2185", "L/SILL PANEL COVER", "8775132000", "0%", "317.28"],
        ["1000", "DOOR FITTING KIT", "Renew", "0%", "10.00"],
        ["1000", "SOUND PAD X1", "Renew", "0%", "3.40"],
        ["1000", "DOOR FOIL X1", "Renew", "0%", "4.00"],
        ["1000", "DOOR FITTING KIT", "Renew", "0%", "10.00"],
        ["1000", "LIGHT MOULDING CLIP", "Renew", "0%", "3.24"],
        ["", "", "", "Sub Total", "1,195.65"],
        ["", "", "", "Deduction from RRP", "-"],
        ["", "", "", "Sundry Parts", "41.85"],
        ["", "", "", "Total Parts", "1,237.50"],
    ]
    add_schedule_table(
        doc, ["Guide No.", "Description", "Part Number", "Betterment", "Price"], parts_rows
    )

    add_heading_line(doc, "EXTRAS")
    extras_rows = [
        ["Corrosion protection", "", "6.00"],
        ["Car Sanitisation", "", "30.00"],
        ["C/Car Class A", "", "0.00"],
        ["Fade Out Thinners", "", "3.50"],
        ["Seam Sealer", "", "3.50"],
        ["Panel Sundries", "", "5.00"],
        ["Body Filler", "", "10.00"],
        ["Lifting Tape", "", "3.75"],
        ["Cavity Wax Remover", "", "6.75"],
        ["Car Care Kit", "", "8.00"],
        ["EPA charge", "", "22.00"],
        ["Tech Data + Methods", "", "38.00"],
        ["Total Extras", "", "136.32"],
    ]
    add_schedule_table(doc, ["Description", "Bet.", "Price"], extras_rows)
    doc.add_paragraph("Claims Details")

    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Assessment Number: D38892222",
            "Version: fhfjdd1\\/2",
            "Full report",
            "Printed: 26/11/2026",
        ],
    )

    add_heading_line(doc, "Calculation")
    add_paragraphs(
        doc,
        [
            "Labour Rate: £38.00",
            "Paint Rate: £68.00",
            "Paint Index: 100.00%",
            "Parts Discount: 0.00%",
            "Overall Discount: 0.00%",
            "Labour — Total Panel/mechanical: £1482.40",
            "Labour — Total Paintwork: £1026.80",
            "Total Labour: £2509.20",
        ],
    )

    add_heading_line(doc, "Summary")
    add_paragraphs(
        doc,
        [
            "Total Paint / Materials Costs: 1029.57",
            "Total Parts: 1237.50",
            "Total Additional Costs: 136.32",
            "Overall Discount: 0.00",
            "Repair Grand Total Excl. VAT: 4912.59",
            "Grand Total Excl. VAT: 4912.59",
            "VAT 20%: 982.52",
            "Grand Total Incl. VAT: 5895.11",
            "Total Due: 5895.11",
        ],
    )

    return doc


def build_repair_invoice_format_1() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "DLAS")
    add_paragraphs(doc, [DLAS_ISSUER_BLOCK, "INVOICE"])
    # No colons: the DLAS header is a label cell beside a value cell. No policy
    # number and no vehicle make/model are printed anywhere on this invoice.
    add_label_grid(
        doc,
        [
            ("Invoice Date", "2/3/2023"),
            ("Invoice Number", "343653726836/1~3538"),
            ("DL Claim number", "245338996/1"),
            ("DL policyholder", "John Doe"),
            ("Vehicle Registration", "AB12XYZ"),
        ],
    )

    add_heading_line(doc, "Parts")
    parts_rows = [
        ["1", "L/R DOOR 1781", "7700332300", "847.73", "847.73"],
        ["1", "L/SILL PANEL COVER 2185", "8775132000", "317.28", "317.28"],
        ["1", "Door Fitting Kit 1000", "Renew", "10.00", "10.00"],
        ["1", "DOOR FOIL X1 1000", "Renew", "4.00", "4.00"],
        ["1", "SOUND PAD X1 1000", "Renew", "3.40", "3.40"],
        ["1", "Door Fitting Kit 1000", "Renew", "10.00", "10.00"],
        ["1", "Light Moulding Clip 1000", "Renew", "3.24", "3.24"],
        ["", "Sundry parts", "3.50%", "", "41.85"],
        ["", "Total Parts", "", "", "1237.50"],
    ]
    add_schedule_table(
        doc, ["Qty", "Description", "Part Number", "Each", "Extended"], parts_rows
    )

    add_heading_line(doc, "Specialist Operation")
    specialist_rows = [
        ["Corrosion protection", "6.00"],
        ["Car Sanitisation", "30.00"],
        ["C/Car Class A", "-"],
        ["Fade Out Thinners", "3.50"],
        ["Seam Sealer", "3.50"],
        ["Panel Sundries", "5.00"],
        ["Body Filler", "10.00"],
        ["Lifting Tape", "3.75"],
        ["Cavity Wax Remover", "6.57"],
        ["Car Care Kit", "8.00"],
        ["E.P.A. Charge", "22.00"],
        ["Tech Data + Methods", "38.00"],
        ["Total", "136.32"],
    ]
    add_schedule_table(doc, ["Specialist Operation", "Cost (£)"], specialist_rows)

    # Page 2 of the client's invoice carries the rolled-up totals and the
    # repairer footer; the page-1 issuer block names the insurer's invoicing
    # department, not the repairer. (`docx_ingest` reflows the replica onto its
    # own pages and does not honour this break, so the extracted text is one
    # page -- the two company blocks are still in document order, which is what
    # `invoice_parser._footer_company` reads.)
    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Total Labour: 2509.20",
            "Total Paint & materials: 1029.57",
            "An amount equivalent to VAT @20%: 982.52",
            "Invoice total: 5895.11",
            "Total Due: 5895.11",
        ],
    )

    add_paragraphs(doc, [INVOICE_TERMS, REPAIRER_FOOTER])
    return doc


# --------------------------------------------------------------------------
# Format 2 -- assessment report (only header, vehicle and labour pages were
# ever photographed for this pair).
# --------------------------------------------------------------------------


def build_auda_format_2_assessment() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "Assessment report")
    add_paragraphs(
        doc,
        [
            "Assessment Number: D38892222",
            "Version: fhfjdd1\\/2",
            "Full report",
            "Printed: 26/11/2026",
        ],
    )

    add_heading_line(doc, "Summary Information")
    doc.add_paragraph("Claim")
    add_grid_table(
        doc,
        [
            ("Assessment Number", "D7576879", "Reference Name", "John Doe"),
            ("First Received", "12/11/2025", "Assigned to", "DL"),
            ("Assessment Status", "Active", "Auth/total loss date", "25/11/2025"),
            ("Authorization Status", "Authorized", "Date of accident", "11/11/2025"),
            ("Work Provider", "DL- Marvin", "Excess", "£0.00"),
            ("Claim Reference", "123456/1", "Able to authorize repairs", "Yes"),
            ("Policy Number", "103466899", "Are the repairs authorized", "Yes"),
            ("Other reference", "", "Date of inspection", ""),
            ("Version", "fhfjdd1\\/2", "Place of inspection", "Repairer"),
            ("Decision date", "25/11/2025", "VAT Status", "Non Taxable"),
        ],
    )

    add_heading_line(doc, "Vehicle Details")
    add_paragraphs(
        doc,
        [
            "Manufacturer: SKODA",
            "Model: KAROQ SE TSI 115]",
            "Model Sheet Number: 80KO",
            "Engine: 1.9 LTR 88/109 KW",
            "Registration Number: A30DRY",
            "VIN Number: ABCD98765432",
            "Registration Month: July",
            "Registration Year: 2018",
            "Odometer: 58882 miles",
        ],
    )

    add_heading_line(doc, "Model Options")
    model_options = (
        "FROM 09/2018 · FRT BUMO CORN RADAR · ULTRASONIC PARK SYS · "
        "1.9 LTR 88/109 KW · RADAR FRONT · PAINTING OFF VEHICLE · "
        "2-COLOUR PAINTING · CLEAR COAT HARD"
    )
    add_paragraphs(doc, [item.strip() for item in model_options.split("·")])
    add_paragraphs(doc, ["Colour:", "TWO COST PEARL/MICA"])

    add_heading_line(doc, "Vehicle Condition")
    add_paragraphs(
        doc,
        [
            "Tyres: Good",
            "Pre accident: Good",
            "Steering: Satisfactory",
            "Brakes: Satisfactory",
            "Severity of impact:",
            "Damage Areas:",
            "Tyres- Depth (MM): Front Left Hand Inner 5mm · Front Right Hand "
            "Inner 5mm · Rear Left hand Inner 5mm · Rear Right Hand Innder 5mm",
        ],
    )

    add_heading_line(doc, "Repair Information")
    add_heading_line(doc, "LABOUR")
    doc.add_paragraph("Time Basis 10 WU=1HR.Price £80.00/HR")
    labour_rows = [
        ["52904A00", "REPAIR LOWER TAILGATE", "40.0"],
        ["865246R77", "REPAIR REAR BUMPER SPOLIER", "20.0"],
        ["865246R77 ZAX", "REPAIR R/R BUMPER", "20.0"],
        ["NO MUMBER", "REPAIR REAR BUMPER", "30.0"],
        ["NO MUMBER", "REMOVE & REFOT BADGE X2", "6.0"],
        ["865246R7", "(BUMPER COVER REMOVED)", "0.0"],
        ["865246R7B", "R+R REAR PARKING AID SENSOR", "1.0"],
        ["865246R7B", "R+R RIGHT REAR FOG LAMP", "1.0"],
        ["991088A00", "RENEW REAR NUMBER PLATE", "1.0"],
        ["991088A00", "RENEW R/INNER TAILLAMP", "1.0"],
        ["", "R+R RIGHT INNER TAILLAMP", "2.0"],
        ["0281", "R+R REAR BUMPER CPL", "5.0"],
        ["0291", "R+R RIGHT TAIL LAMP", "2.0"],
        ["0300", "RENEW R/TAILLAMP (REMOVE)", "2.0"],
        ["1000", "R+R RIGHT FRONT DOOR LAMP", "2.0"],
        ["1000", "DIAGNOSE AFTER REPAIR", "3.0"],
        ["1000", "DIAGNOSE BEFORE REPAIR", "3.0"],
        ["", "Total Work Units", "139.0"],
        ["", "TOTAL PANEL/MECHANICAL LABOUR 13.9 HOURS", "£1112.00"],
    ]
    add_schedule_table(doc, ["Guide Number", "Description", "WU"], labour_rows)

    return doc


def build_invoice_2_request_for_payment() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "DL Assistance")
    add_paragraphs(doc, [DLAS_ISSUER_BLOCK, "** Request for Payment **"])
    add_label_grid(
        doc,
        [
            ("Invoice Date", "26/11/2025"),
            ("Invoice Number", "22564547648/1~AJ123456"),
        ],
    )

    add_grid_table(
        doc,
        [
            ("Reference Name", "John Doe", "Vehicle Registration", "A30DRY"),
            ("Claim No", "123456/1", "Vehicle Make", "SKODA"),
            ("Policy No", "103466899", "Vehicle Model", "KAROQ SE TSI 115]"),
            ("Assessment Ref", "BOY1537", "Excess", "£0.00"),
            ("Collection Date", "", "Insured VAT Status", "Non Taxable"),
        ],
    )

    body_rows = [
        ["Total Parts Amount", "448.91", "89.78"],
        ["Total Paint & Materials Amount", "1034.02", "206.80"],
        ["Total Labour Amount", "2008.00", "401.60"],
        ["Total", "3490.93", "698.18"],
        ["Additional charges", "627.00", "125.40"],
        ["Deductions", "0.00", "0.00"],
        ["Invoice Total", "4941.52", ""],
        ["Policy Excess Paid by Customer-", "0.00", ""],
        ["Total Due", "4941.52", ""],
    ]
    add_schedule_table(
        doc, ["Item Description", "Cost", "Sum Equivalent to VAT @20%"], body_rows
    )

    add_paragraphs(doc, [REPAIRER_FOOTER])
    return doc


# --------------------------------------------------------------------------
# Format 7 -- assessment report. Re-uses format 1's labour and paint rows
# under a new identity and new parts/extras prices; every printed-vs-rows
# discrepancy from the transcription is reproduced verbatim.
# --------------------------------------------------------------------------


def build_auda_format_7_assessment() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "Assessment report")
    add_paragraphs(
        doc,
        [
            "Assessment Number: T4592861",
            "Version:",
            "Full report",
            "Printed: 11/09/2026",
        ],
    )

    add_heading_line(doc, "Summary Information")
    doc.add_paragraph("Claim")
    add_grid_table(
        doc,
        [
            ("Assessment Number", "T4592861", "Reference Name", "Oliver Reed"),
            ("First Received", "12/11/2025", "Assigned to", "DL"),
            ("Assessment Status", "Active", "Auth/total loss date", ""),
            ("Authorization Status", "Authorized", "Date of accident", "30/12/2025"),
            ("Work Provider", "DL- Marvin", "Excess", "£0.00"),
            ("Claim Reference", "426953180/3", "Able to authorize repairs", "Yes"),
            ("Policy Number", "PL-739284", "Are the repairs authorized", "Yes"),
            ("Other reference", "", "Date of inspection", ""),
            ("Version", "TRN-04/1", "Place of inspection", "Repairer"),
            ("Decision date", "25/11/2025", "VAT Status", "Non Taxable"),
        ],
    )

    add_heading_line(doc, "Vehicle Details")
    add_paragraphs(
        doc,
        [
            "Manufacturer: HYUNDAI",
            "Model: 140 SE Nav",
            "Model Sheet Number: 3071",
            "Engine: 1.7 LTR 85 KW",
            "Registration Number: JK21MNO",
            "VIN Number: TRN7429685310",
            "Registration Month: march",
            "Registration Year: 2018",
            "Odometer: 576882 miles",
        ],
    )

    add_heading_line(doc, "Model Options")
    model_options = (
        "FROM 06/2017 · MODEL i30 · HEAT ABSORBING GLASS · WITH A/C · "
        "DRIVER SEAT HEIGHT · WITHOUT ALARM · ELECTRIC FOLDING MIRROR · "
        "HEATED WINDSCREEN · FRONT / REAR PARKING SENSOR · REAR CAMERA · "
        "STEERING WHEEL CONTROLS · START / STOP SYSTEM · CRUISE CONTROL · "
        "DOOR COVERS · TIRE REPAIR KIT · DIMENSION 570 R/O · BASECOAT CLEAR"
    )
    add_paragraphs(doc, [item.strip() for item in model_options.split("·")])

    add_heading_line(doc, "Vehicle Condition")
    add_paragraphs(
        doc,
        [
            "Tyres: Good",
            "Pre accident: Good",
            "Steering: Satisfactory",
            "Brakes: Satisfactory",
            "Severity of impact:",
            "Damage Areas:",
            "Tyres- Depth (MM): Front Left Hand Inner: 4mm · Front Right Hand "
            "Inner: 4mm · Rear Left hand Inner: 4mm · Rear Right Hand Innder: 4mm",
            "Addresses — Insured: Oliver Reed",
            'Note: "Using Manufacturer Times"',
        ],
    )

    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Assessment Number: T4592861",
            "Version: TRN-04/1",
            "Full report",
            "Printed: 11/09/2026",
        ],
    )

    add_heading_line(doc, "Repair Information")
    add_heading_line(doc, "LABOUR")
    doc.add_paragraph("Time Basis 10 WU=1HR.")
    # Identical 25-row operation list to format 1: rows sum to 101 WU, but
    # the printed total here is 300 (not 218) -- reproduced as printed.
    labour_rows = [
        ["52803000", "A30 - R/R OUTER VEHICLE C/R", "10"],
        ["87751000", "R + R SILL COVER, LH", "2"],
        ["87751000", "R + R SILL COVER", "2"],
        ["82510R00", "R + R LEFT FRONT OUTER WINDOW CHANNEL", "2"],
        ["82650R00", "R + R LEFT FRONT OUTER DOOR HANDLE", "2"],
        ["87610R00", "R + R DOOR MIRROR", "2"],
        ["87320R00", "R + R LEFT WEATHERSTRIP", "2"],
        ["", "REMOVE ATTACHED PARTS", "4"],
        ["NO NUMBER", "BODY WORK FOR LEFT FRONT DOOR", "4"],
        ["82300R00", "R + R UPPER WEATHER STRIP", "2"],
        ["82410R00", "R + R OUTER SEAL AND LAP", "2"],
        ["82520R00", "R + R LEFT FRONT INNER GLASS", "2"],
        ["82610R00", "R + R LEFT REAR INNER / DOOR SHELL", "2"],
        ["", "R + R BELT MOULDING", "2"],
        ["", "R + R SIDE MOULDING", "3"],
        ["", "REMOVE / REFIT DOOR TRIM", "3"],
        ["", "DISCONNECT / RECONNECT VEHICLE BATTERY", "1"],
        ["", "REPROGRAM / REINITIALISE VEHICLE SYSTEMS", "1"],
        ["1000", "R + R / REFIT FRONT DOOR INTERNALS", "5"],
        ["1000", "REMOVE / REFIT DOOR PANELS", "5"],
        ["1000", "REPAIR LEFT REAR / QUARTER PANEL", "13"],
        ["1000", "REPAIR LEFT SILL / BODY AREA", "15"],
        ["1000", "PULL / ALIGN REPAIR SYSTEM", "5"],
        ["1000", "SET UP MIRACLE PULL SYSTEM", "5"],
        ["1000", "CORROSION PROTECTION / 2 SIDES", "5"],
        ["", "Total Work Units", "300"],
    ]
    add_schedule_table(doc, ["Number", "Description", "WU"], labour_rows)

    add_heading_line(doc, "PAINT WORK")
    # Identical 16-row list to format 1: rows sum to 151 WU, printed total
    # here is 113.2 (not 151.0) -- reproduced as printed.
    paint_rows = [
        ["1781", "L/R DOOR NEW PART PAINTING", "15"],
        ["2185", "L/SILL PANEL COVER NEW PART FRONT K2", "7"],
        ["2185", "OUTER SILL PANEL REPAIR PAINTING", "10"],
        ["3465", "L/R OUTER QUARTER PANEL REPAIR PAINTING", "24"],
        ["1521", "L/R INNER PANEL PAINTING", "26"],
        ["1521", "L/R LOWER DOOR SURFACE PAINT", "8"],
        ["2279", "LEFT B-PILLAR / SURFACE PAINT", "4"],
        ["4390", "L/R ROOF SECTION SURFACE PAINT", "5"],
        ["", "FUEL FILLER FLAP SURFACE PAINT", "3"],
        ["1000", "REAR WING / PANEL BEFORE PAINTING", "5"],
        ["1000", "FINAL COLOUR MATCH", "2"],
        ["1000", "ALL FADE OUT POLISH", "5"],
        ["1000", "L/R SIDE GLASS MASK", "3"],
        ["1000", "SEAM SEAL AS REQUIRED PAINTING", "3"],
        ["1000", "TRIM / BODY REPAIR PAINTING", "3"],
        ["", "PREPARATION FOR PRE-PAINTING", "28"],
        ["", "Total Work Units", "113.2"],
    ]
    add_schedule_table(doc, ["Number", "Description", "WU"], paint_rows)

    add_heading_line(doc, "PARTS")
    # Rows sum to 908.30; the printed Sub Total is 907.70 (60p short).
    parts_rows = [
        ["1781", "L/R DOOR", "7700332300", "0%", "645.00"],
        ["2185", "L/SILL PANEL COVER", "8775132000", "0%", "240.00"],
        ["1000", "DOOR FITTING KIT", "Renew", "0%", "7.60"],
        ["1000", "SOUND PAD X1", "Renew", "0%", "2.60"],
        ["1000", "DOOR FOIL X1", "Renew", "0%", "3.00"],
        ["1000", "DOOR FITTING KIT", "Renew", "0%", "7.60"],
        ["1000", "LIGHT MOULDING CLIP", "Renew", "0%", "2.50"],
        ["", "", "", "Sub Total", "907.70"],
        ["", "", "", "Deduction from RRP", "-"],
        ["", "", "", "Sundry Parts", "31.30"],
        ["", "", "", "Total Parts", "939.00"],
    ]
    add_schedule_table(
        doc, ["Guide No.", "Description", "Part Number", "Betterment", "Price"], parts_rows
    )

    add_heading_line(doc, "EXTRAS")
    # Rows sum to 103.80; printed total 104.00 (20p over).
    extras_rows = [
        ["Corrosion protection", "", "4.60"],
        ["Car Sanitisation", "", "22.80"],
        ["C/Car Class A", "", "0.00"],
        ["Fade Out Thinners", "", "2.70"],
        ["Seam Sealer", "", "2.70"],
        ["Panel Sundries", "", "3.80"],
        ["Body Filler", "", "7.60"],
        ["Lifting Tape", "", "2.90"],
        ["Cavity Wax Remover", "", "5.10"],
        ["Car Care Kit", "", "6.10"],
        ["EPA charge", "", "16.70"],
        ["Tech Data + Methods", "", "28.80"],
        ["Total Extras", "", "104.00"],
    ]
    add_schedule_table(doc, ["Description", "Bet.", "Price"], extras_rows)
    doc.add_paragraph("Claims Details")

    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Assessment Number: T4592861",
            "Version: TRN-04/1",
            "Full report",
            "Printed: 11/09/2026",
        ],
    )

    add_heading_line(doc, "Calculation")
    add_paragraphs(
        doc,
        [
            "Labour Rate: £38.00",
            "Paint Rate: £68.00",
            "Paint Index: 100.00%",
            "Parts Discount: 0.00%",
            "Overall Discount: 0.00%",
            "Labour — Total Panel/mechanical: £1140.00",
            "Labour — Total Paintwork: £770.00",
            "Total Labour: £1910.00",
        ],
    )

    add_heading_line(doc, "Summary")
    add_paragraphs(
        doc,
        [
            "Total Paint / Materials Costs: 785.00",
            "Total Parts: 939.00",
            "Total Additional Costs: 104.00",
            "Overall Discount: 0.00",
            "Repair Grand Total Excl. VAT: 3738.00",
            "Grand Total Excl. VAT: 3738.00",
            "VAT 20%: 747.60",
            "Grand Total Incl. VAT: 4485.60",
            "Total Due: 4485.60",
        ],
    )

    return doc


def build_repair_invoice_format_7() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "DLAS")
    add_paragraphs(doc, [DLAS_ISSUER_BLOCK, "INVOICE"])
    add_label_grid(
        doc,
        [
            ("Invoice Date", "2/3/2023"),
            # Same invoice number as pair 1's invoice, despite a different
            # claim -- the client's own duplicate, reproduced verbatim.
            ("Invoice Number", "343653726836/1~3538"),
            ("DL Claim number", "426953180/3"),
            ("DL policyholder", "Oliver Reed"),
            ("Vehicle Registration", "JK21MNO"),
        ],
    )
    # No policy number and no vehicle make/model anywhere on this invoice --
    # deliberate, per the transcription; the gap-fill logic must recover them
    # from the assessment.

    add_heading_line(doc, "Parts")
    parts_rows = [
        ["1", "L/R DOOR 1781", "7700332300", "645.00", "645.00"],
        ["1", "L/SILL PANEL COVER 2185", "8775132000", "240.00", "240.00"],
        ["1", "Door Fitting Kit 1000", "Renew", "7.60", "7.60"],
        ["1", "DOOR FOIL X1 1000", "Renew", "3.00", "3.00"],
        ["1", "SOUND PAD X1 1000", "Renew", "2.60", "2.60"],
        ["1", "Door Fitting Kit 1000", "Renew", "7.60", "7.60"],
        ["1", "Light Moulding Clip 1000", "Renew", "2.50", "2.50"],
        ["", "Sundry parts", "3.50%", "", "31.30"],
        ["", "Total Parts", "", "", "939.00"],
    ]
    add_schedule_table(
        doc, ["Qty", "Description", "Part Number", "Each", "Extended"], parts_rows
    )

    add_heading_line(doc, "Specialist Operation")
    specialist_rows = [
        ["Corrosion protection", "4.60"],
        ["Car Sanitisation", "22.80"],
        ["C/Car Class A", "0.00"],
        ["Fade Out Thinners", "2.70"],
        ["Seam Sealer", "2.70"],
        ["Panel Sundries", "3.80"],
        ["Body Filler", "7.60"],
        ["Lifting Tape", "2.90"],
        ["Cavity Wax Remover", "5.10"],
        ["Car Care Kit", "6.10"],
        ["E.P.A. Charge", "16.70"],
        ["Tech Data + Methods", "28.80"],
        ["Total", "104.00"],
    ]
    add_schedule_table(doc, ["Specialist Operation", "Cost (£)"], specialist_rows)

    # Page 2 carries the totals, the validation note and the repairer footer
    # (see the note on the same break in `build_repair_invoice_format_1`).
    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Total Labour: 1910.00",
            "Total Paint & materials: 785.00",
            "An amount equivalent to VAT @20%: 747.60",
            "Invoice total: 4485.60",
            "Total Due: 4485.60",
        ],
    )

    doc.add_paragraph(
        "Validation note: Verified against Assessment T4592861 / Claim "
        "Reference 426953180/3 for Oliver Reed. All invoice fields and "
        "breakups match exactly: Parts line items total £907.70 plus "
        "Sundry Parts £31.30 = Total Parts £939.00; Specialist Operations "
        "total £104.00; Total Labour £1,910.00; Total Paint / Materials "
        "Costs £785.00; VAT £747.60; Invoice Total / Total Due £4,485.60."
    )

    add_paragraphs(doc, [INVOICE_TERMS, REPAIRER_FOOTER])
    return doc


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------

MANIFEST: list[dict[str, Any]] = [
    {
        "filename": "DL_Auda_format_1_assessment.docx",
        "document_kind": "engineer_assessment",
        "pair_id": 1,
        "claim_reference": "245338996/1",
        "policy_number": "PH",
        "registration": "AB12XYZ",
        "vehicle_make": "HYUNDAI",
        "vehicle_model": "140 SE Nav",
        "assessment_number": "D7576879",
        "assessment_ref": None,
        "invoice_number": None,
        "section_totals": {
            "labour": "2509.20",
            "paint_materials": "1029.57",
            "parts": "1237.50",
            "extras": "136.32",
        },
        "gross_total": "5895.11",
    },
    {
        "filename": "DL_Repair_Invoice_format_1.docx",
        "document_kind": "repair_invoice",
        "pair_id": 1,
        "claim_reference": "245338996/1",
        "policy_number": None,
        "registration": "AB12XYZ",
        "vehicle_make": None,
        "vehicle_model": None,
        "assessment_number": None,
        "assessment_ref": None,
        "invoice_number": "343653726836/1~3538",
        "section_totals": {
            "parts": "1237.50",
            "extras": "136.32",
            "labour": "2509.20",
            "paint_materials": "1029.57",
        },
        "gross_total": "5895.11",
    },
    {
        "filename": "DL_Auda_format_2_assessment.docx",
        "document_kind": "engineer_assessment",
        "pair_id": 2,
        "claim_reference": "123456/1",
        "policy_number": "103466899",
        "registration": "A30DRY",
        "vehicle_make": "SKODA",
        "vehicle_model": "KAROQ SE TSI 115]",
        "assessment_number": "D7576879",
        "assessment_ref": None,
        "invoice_number": None,
        "section_totals": {"labour": "1112.00"},
        "gross_total": None,
    },
    {
        "filename": "DL_Invoice_2_request_for_payment.docx",
        "document_kind": "repair_invoice",
        "pair_id": 2,
        "claim_reference": "123456/1",
        "policy_number": "103466899",
        "registration": "A30DRY",
        "vehicle_make": "SKODA",
        "vehicle_model": "KAROQ SE TSI 115]",
        "assessment_number": None,
        "assessment_ref": "BOY1537",
        "invoice_number": "22564547648/1~AJ123456",
        "section_totals": {
            "parts": "448.91",
            "paint_materials": "1034.02",
            "labour": "2008.00",
            "additional": "627.00",
        },
        "gross_total": "4941.52",
    },
    {
        "filename": "DL_Auda_format_7_assessment.docx",
        "document_kind": "engineer_assessment",
        "pair_id": 7,
        "claim_reference": "426953180/3",
        "policy_number": "PL-739284",
        "registration": "JK21MNO",
        "vehicle_make": "HYUNDAI",
        "vehicle_model": "140 SE Nav",
        "assessment_number": "T4592861",
        "assessment_ref": None,
        "invoice_number": None,
        "section_totals": {
            "labour": "1910.00",
            "paint_materials": "785.00",
            "parts": "939.00",
            "extras": "104.00",
        },
        "gross_total": "4485.60",
    },
    {
        "filename": "DL_Repair_Invoice_format_7.docx",
        "document_kind": "repair_invoice",
        "pair_id": 7,
        "claim_reference": "426953180/3",
        "policy_number": None,
        "registration": "JK21MNO",
        "vehicle_make": None,
        "vehicle_model": None,
        "assessment_number": None,
        "validation_note_assessment_number": "T4592861",
        "assessment_ref": None,
        "invoice_number": "343653726836/1~3538",
        "section_totals": {
            "parts": "939.00",
            "extras": "104.00",
            "labour": "1910.00",
            "paint_materials": "785.00",
        },
        "gross_total": "4485.60",
    },
]

BUILDERS: dict[str, Any] = {
    "DL_Auda_format_1_assessment.docx": build_auda_format_1_assessment,
    "DL_Repair_Invoice_format_1.docx": build_repair_invoice_format_1,
    "DL_Auda_format_2_assessment.docx": build_auda_format_2_assessment,
    "DL_Invoice_2_request_for_payment.docx": build_invoice_2_request_for_payment,
    "DL_Auda_format_7_assessment.docx": build_auda_format_7_assessment,
    "DL_Repair_Invoice_format_7.docx": build_repair_invoice_format_7,
}


_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _normalise_zip_timestamps(path) -> None:
    """Rewrite the .docx archive with fixed entry timestamps.

    python-docx stamps every zip member with the current time, so a rerun
    produced six binary diffs even though the content was identical. Fixing the
    timestamps makes the build byte-idempotent, which is what lets a CI check
    assert the committed fixtures are current.
    """

    with zipfile.ZipFile(path) as source:
        members = [(info, source.read(info.filename)) for info in source.infolist()]
    with zipfile.ZipFile(path, "w") as target:
        for info, payload in members:
            fixed = zipfile.ZipInfo(info.filename, date_time=_FIXED_ZIP_TIME)
            fixed.compress_type = info.compress_type
            fixed.external_attr = info.external_attr
            target.writestr(fixed, payload)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for entry in MANIFEST:
        filename = entry["filename"]
        builder = BUILDERS[filename]
        document = builder()
        target = OUTPUT_DIR / filename
        document.save(target)
        _normalise_zip_timestamps(target)
        print(f"Wrote {target}")

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(MANIFEST, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
