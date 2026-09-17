"""Build the client-format `.docx` fixtures used by the invoice <-> assessment
matching work (see `.claude/team-runs/invoice-assessment-matching-plan.md`, Task 2).

These files replicate -- as faithfully as `python-docx` allows -- all seven
DL Auda/DLAS claim pairs plus the EXL demo pair, transcribed from the client's
phone photos:

    client-formats/2026-09-15_dl-auda-format-1-assessment-report/
    client-formats/2026-09-15_dl-auda-format-2-engineer-report-2/
    client-formats/2026-09-16_dl-auda-format-3-engineer-report/
    client-formats/2026-09-16_dl-auda-format-4-engineer-report/
    client-formats/2026-09-16_dl-auda-format-5-engineer-report/
    client-formats/2026-09-16_dl-auda-format-6-engineer-report/
    client-formats/2026-09-15_dl-auda-format-7-engineer-report/
    client-formats/2026-09-15_auda-2-engineer-report/       (the EXL demo pair)

Every value below is taken verbatim from the corresponding `*_transcription.md`
file, including the documents' own internal flaws (mismatched totals,
duplicate invoice numbers, conflicting assessment numbers, an embedded
"Validation note" paragraph, etc.) -- those flaws are the point: they are what
the extraction and pairing logic must be tested against. No real client file
is read, written, or committed by this script; there are none in this repo.

Usage (from backend/):

    uv run python scripts/build_client_format_fixtures.py

Writes 16 `.docx` files plus `manifest.json` into `sample-data/client-formats/`
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
    # Centre-aligned "Label: value" paragraphs, exactly as the photograph of
    # the client's header shows them (see the CORRECTION note in
    # client-formats/REQUIREMENTS_2026-09-16_visibility-pairing-and-clean-slate.md).
    # No policy number and no vehicle make/model are printed on this invoice.
    add_paragraphs(
        doc,
        [
            "Invoice Date: 2/3/2023",
            "Invoice Number: 343653726836/1~3538",
            "DL Claim number: 245338996/1",
            "DL policyholder: John Doe",
            "Vehicle Registration : AB12XYZ",
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
    # The "Request for Payment" reference grid below prints no colons, but its
    # invoice date and number are colon paragraphs on the client's document.
    add_paragraphs(
        doc,
        [
            "Invoice Date: 26/11/2025",
            "Invoice Number: 22564547648/1~AJ123456",
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
# Format 3 -- assessment report. First pair in the corpus with two new
# sections (`Material cost paint`, `Additional costs`) and a negative parts
# adjustment (`DEDUCTION FROM RRP`). The page headers disagree with each
# other (D38892111 on the title/PARTS/PAINT WORK pages, D38892222 on the
# LABOUR page) and the Calculation block's Total Parts (£13.18) disagrees
# with the PARTS page's own Total Parts (£13.56) -- both reproduced verbatim,
# per client-formats/2026-09-16_dl-auda-format-3-engineer-report/.
# --------------------------------------------------------------------------


def build_auda_format_3_assessment() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "Assessment report")
    add_paragraphs(
        doc,
        [
            "Assessment Number: D38892111",
            "Version: fhfjdd1\\/2",
            "Full report",
            "Printed: 08/12/2026",
        ],
    )

    add_heading_line(doc, "Summary Information")
    doc.add_paragraph("Claim")
    add_grid_table(
        doc,
        [
            ("Assessment Number", "D38892111", "Reference Name", "John Doe"),
            ("First Received", "13/01/2025", "Assigned to", "DL"),
            ("Assessment Status", "Active", "Auth/total loss date", "07/12/2026"),
            ("Authorization Status", "Authorized", "Date of accident", "20/12/2025"),
            ("Work Provider", "DL- Marvin", "Excess", "£0.00"),
            ("Claim Reference", "354647/1", "Able to authorize repairs", "Yes"),
            ("Policy Number", "103466899", "Are the repairs authorized", "Yes"),
            ("Other reference", "", "Date of inspection", ""),
            ("Version", "avdhj\\/2", "Place of inspection", "Repairer"),
            ("Decision date", "25/11/2025", "VAT Status", "Non Taxable"),
        ],
    )

    add_heading_line(doc, "Vehicle Details")
    add_paragraphs(
        doc,
        [
            "Manufacturer: SEAT",
            "Model: IBIZA",
            "Model Sheet Number: 80KO",
            "Engine: 1.4",
            "Registration Number: AM06TAH",
            "VIN Number: ABCD987889",
            "Registration Month: July",
            "Registration Year: 2018",
            # Printed with the space in the source document; kept verbatim.
            "Odometer: 1156 67 miles",
        ],
    )

    add_heading_line(doc, "Model Options")
    model_options = (
        "FROM 09/2011 · AUTO AIR CON · ULTRASONIC PARK SYS · RAIN SENSOR · "
        "RADAR FRONT · PAINTING OFF VEHICLE · 2-COLOUR PAINTING"
    )
    add_paragraphs(doc, [item.strip() for item in model_options.split("·")])
    add_paragraphs(doc, ["Colour: Blue", "CLEAR COAT HARD", "TWO COST PEARL/MICA"])

    add_heading_line(doc, "Vehicle Condition")
    add_paragraphs(
        doc,
        [
            "Tyres: Good",
            "Pre accident: Good",
            "Steering: Satisfactory",
            "Brakes: Satisfactory",
            "Severity of impact:",
            "Damage Areas: G left Hand side · F left hand rear",
            "Tyres- Depth (MM): Front Left Hand Inner 6mm · Front Right Hand "
            "Inner 6mm · Rear Left hand Inner 6mm · Rear Right Hand Inner 6mm",
            "Addresses — Insured: John Doe",
        ],
    )

    # The LABOUR page prints a different assessment number (D38892222) than
    # the title page and the PARTS/PAINT WORK page below -- the client's own
    # inconsistency, reproduced verbatim (see transcription note above).
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
    doc.add_paragraph("Time Basis 10 WU=1HR.Price £83.28/HR")
    labour_rows = [
        ["52904A78", "NS DOOR HINGE BOLTS RENEW / INCLUDES ADJUST DOOR", "0.0"],
        ["865246", "R +R L/F DOOR", "3.0"],
        ["865R77 ZAX", "REPAIR L/F DOOR TO WINDOW", "30.0"],
        ["NO MUMBER", "REPAIR L/F WING", "10.0"],
        ["NO MUMBER", "R +R ELCETRIC DOOR MIRROR", "2.0"],
        ["8246R7", "R +R L/F DOOR CHANNEL MOULDINGS", "2.0"],
        ["5246R7B", "R +R L/F FRONT DOOR HANDLE", "2.0"],
        ["86246R7B", "CHECK AND ROAD TEST STD", "3.0"],
        ["99088A00", "REPAIR L/R SIDE PANEL", "25.0"],
        ["991088A00", "REMOVE AND REFIT RELEASE REAR BUMPER", "3.0"],
        ["4556", "REMOVE AND REFIT RELEASE FRONT BUMPER", "3.0"],
        ["0281", "R + R L OUTER REAR LAMP", "2.0"],
        ["0291", "R + R L OUTER MIRROR GLASS", "2.0"],
        ["0300", "R + R LS FLASHER LAMP", "2.0"],
        # Rows sum to 89.0, matching the printed Total Work Units. The
        # printed "9.9 HOURS £741.00" line is nevertheless wrong -- 89 WU is
        # 8.9 hours and £741.19, which is what the Calculation block and the
        # Grand Total both use -- reproduced verbatim.
        ["", "Total Work Units", "89.0"],
        ["", "TOTAL PANEL/MECHANICAL LABOUR 9.9 HOURS", "£741.00"],
    ]
    add_schedule_table(doc, ["Guide Number", "Description", "WU"], labour_rows)

    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Assessment Number: D38892111",
            "Version: fhfjdd1\\/2",
            "Full report",
            "Printed: 08/12/2026",
        ],
    )

    add_heading_line(doc, "PAINT WORK")
    doc.add_paragraph("Time Basis 10 WU=1HR.Price £83.28/HR")
    paint_rows = [
        ["1000", "LF DOOR TO WINDOW REPAIR PAINTING >50%", "26.0"],
        ["1000", "LF WING REPAIR PAINTING <50%", "10.0"],
        ["1000", "PREPARATION FOR PREPAINTING", "31.0"],
        ["1000", "DETAILED MASKING REPAIR PAINTING <50%", "3.0"],
        ["1000", "LF DOR HANDLE SURFACE PAINT PLAST", "3.0"],
        ["1000", "LR SIDE PANEL REPAIR PAINT <50%", "21.0"],
        ["", "LDOOR MIRROR HSG REPAIR PAINT PLASTIC", "9.0"],
        ["", "Total Work Units", "103.0"],
        ["", "Total Paint Labour", "£857.78"],
    ]
    add_schedule_table(doc, ["Number", "Description", "WU"], paint_rows)

    # NEW: no earlier format itemised paint materials. The final line here
    # is exactly half of its own subtotal (768.37 / 2 = 384.185) with zero
    # uplift and zero discount above it -- unexplained, and reproduced
    # verbatim; £384.18 is nevertheless what the Calculation block and the
    # Grand Total both use.
    add_heading_line(doc, "Material cost paint")
    material_cost_paint_rows = [
        ["Total paint Cost", "603.19"],
        ["Sundry Paint Material", "114.68"],
        ["Pre-Painting sundry materials", "50.50"],
        ["Total Excluding Pearlescent uplift", "768.37"],
        ["Pearlescent Uplift", "0.00"],
        ["Discounted by", "0.00"],
        ["Total paint and Material cost", "384.18"],
    ]
    add_schedule_table(doc, ["Line", "Value (£)"], material_cost_paint_rows)

    add_heading_line(doc, "PARTS")
    # A subtracted "DEDUCTION FROM RRP" adjustment row -- formats 1 and 7 only
    # ever had a positive sundry-parts uplift. 14.40 - 1.30 + 0.46 = 13.56.
    # The document prints the amount unsigned; the label carries the sign.
    parts_rows = [
        ["1000", "NS door hinge bolts", "Renew", "", "14.40"],
        ["", "", "", "SUB TOTAL", "14.40"],
        ["", "", "", "DEDUCTION FROM RRP (9.00%)", "1.30"],
        ["", "", "", "SUNDRY PARTS", "0.46"],
        ["", "", "", "Total Parts", "13.56"],
    ]
    add_schedule_table(
        doc, ["Guide No.", "Description", "Part Number", "Bet.", "Price"], parts_rows
    )

    add_heading_line(doc, "EXTRAS")
    extras_rows = [
        ["ANTI CORROSION PROTE", "0%", "4.00"],
        ["", "", ""],
        ["Total Extras", "", "4.00"],
    ]
    add_schedule_table(doc, ["Description", "Bet.", "Price"], extras_rows)

    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Assessment Number: D38892111",
            "Version: fhfjdd1\\/2",
            "Full report",
            "Printed: 08/12/2026",
        ],
    )

    add_heading_line(doc, "Calculation")
    # Total Parts £13.18 here contradicts the PARTS page's £13.56 above; the
    # Grand Total below proves £13.56 is the figure actually used -- both
    # reproduced verbatim.
    add_paragraphs(
        doc,
        [
            "Total Panel/Mechanical: £741.19",
            "Total Paintwork: £857.78",
            "Total Labour: £1598.97",
            "Total Paint/material cost: £384.18",
            "Total Parts: £13.18",
        ],
    )

    add_heading_line(doc, "Additional costs")
    # This £4.00 is the same £4.00 as Total Extras above (the ANTI
    # CORROSION PROTE line), shown a second way; the Grand Total counts it
    # once.
    add_paragraphs(
        doc,
        [
            "Corrosion Protection Materials External: £0.00",
            "Cost of specialist: £4.00",
            "Total Additional Cost: £4.00",
        ],
    )

    add_heading_line(doc, "Subject to check")
    add_paragraphs(
        doc,
        [
            "Subject to check: £0.00",
            "Overall discount: £0.00",
            "Total Deductions: £0.00",
        ],
    )

    add_heading_line(doc, "Grand total")
    # "Grand Total Excl VAT" is printed twice on the source document -- the
    # second occurrence is actually the Incl VAT figure. VAT Status above
    # reads "Non Taxable" yet VAT is charged. Both reproduced verbatim.
    add_paragraphs(
        doc,
        [
            "Grand Total Excl VAT: £2000.71",
            "VAT at 20%: £400.14",
            "Grand Total Excl VAT: £2400.85",
            "Excess: £0.00",
        ],
    )

    return doc


def build_invoice_3_request_for_payment() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "DL Assistance")
    add_paragraphs(doc, [DLAS_ISSUER_BLOCK, "** Request for Payment **"])
    add_paragraphs(
        doc,
        [
            "Invoice Date: 08/02/2025",
            "Invoice Number: 132467/1~FT56678",
        ],
    )

    add_grid_table(
        doc,
        [
            ("Reference Name", "John Doe", "Vehicle Registration", "AM06TAH"),
            ("Claim No", "354647/1", "Vehicle Make", "SEAT"),
            ("Policy No", "103466899", "Vehicle Model", "IBIZA"),
            ("Assessment Ref", "I535377", "Excess", "£0.00"),
            ("Collection Date", "04/02/2026", "Insured VAT Status", "Non Taxable"),
        ],
    )

    body_rows = [
        ["Total Parts Amount", "13.56", "2.71"],
        ["Total Paint & Materials Amount", "384.18", "76.84"],
        ["Total Labour Amount", "1598.97", "319.79"],
        ["Total", "1996.71", "399.34"],
        ["Additional charges", "4.00", "0.80"],
        ["Deductions", "0.00", "0.00"],
        ["Total Sum Equivalent to VAT @20%", "400.14", ""],
        ["Invoice Total", "2400.85", ""],
        ["Policy Excess Paid by Customer-", "0.00", ""],
        ["Total Due", "2400.85", ""],
    ]
    add_schedule_table(
        doc, ["Item Description", "Cost", "Sum Equivalent to VAT @20%"], body_rows
    )

    add_paragraphs(doc, [REPAIRER_FOOTER])
    return doc


# --------------------------------------------------------------------------
# Format 4 -- assessment report. Structurally closest to format 3 (same
# `Material cost paint` table and `Additional costs` / `Subject to check` /
# `Deductions` tail) but much larger and fully itemised. Source typos kept
# (NECESSAY, EDGW, ROGHT, WHEELARCF, INDCATOR, STATIS). See
# client-formats/2026-09-16_dl-auda-format-4-engineer-report/.
# --------------------------------------------------------------------------


def build_auda_format_4_assessment() -> DocxDocumentType:
    doc = _new_document()

    # Unlike formats 1, 3 and 7, the assessment number is consistent across
    # every page header here -- the page-header Version (ukvvjkj678) still
    # disagrees with the Summary grid's Version (avdhj\/2), same hazard as
    # format 3.
    header_lines = [
        "Assessment Number: D067789900",
        "Version: ukvvjkj678",
        "Full report",
        "Printed: 27/04/2026",
    ]

    add_heading_line(doc, "Assessment report")
    add_paragraphs(doc, header_lines)

    add_heading_line(doc, "Summary Information")
    doc.add_paragraph("Claim")
    add_grid_table(
        doc,
        [
            ("Assessment Number", "D067789900", "Reference Name", "John Doe"),
            ("First Received", "01/04/2025", "Assigned to", "DL"),
            ("Assessment Status", "Active", "Auth/total loss date", "26/04/2026"),
            ("Authorization Status", "Authorized", "Date of accident", "01/04/2026"),
            ("Work Provider", "DL- Marvin", "Excess", "£0.00"),
            ("Claim Reference", "1111111/1", "Able to authorize repairs", "Yes"),
            ("Policy Number", "9865433", "Are the repairs authorized", "Yes"),
            ("Other reference", "", "Date of inspection", ""),
            ("Version", "avdhj\\/2", "Place of inspection", "Repairer"),
            ("Decision date", "26/02/2026", "VAT Status", "Non Taxable"),
        ],
    )

    add_heading_line(doc, "Vehicle Details")
    # Model Sheet Number is blank on this format -- a deliberate regression
    # case (the shape that produced the "AB12XYZ WITH A/C" contamination
    # elsewhere in this corpus). Do not fill it in.
    add_paragraphs(
        doc,
        [
            "Manufacturer: FORD",
            "Model: Puma",
            "Model Sheet Number:",
            "Engine: 1.0",
            "Registration Number: PD73UUF",
            "VIN Number: AWD987889",
            "Registration Month: July",
            "Registration Year: 2024",
            "Odometer: 11567 miles",
        ],
    )

    add_heading_line(doc, "Model Options")
    model_options = (
        "FROM 09/2011 · AUTO AIR CON · ULTRASONIC PARK SYS · RAIN SENSOR · "
        "RADAR FRONT · PAINTING OFF VEHICLE · 2-COLOUR PAINTING"
    )
    add_paragraphs(doc, [item.strip() for item in model_options.split("·")])
    add_paragraphs(doc, ["Colour: Grey", "CLEAR COAT HARD", "TWO COST PEARL/MICA"])

    add_heading_line(doc, "Vehicle Condition")
    add_paragraphs(
        doc,
        [
            "Tyres: Good",
            "Pre accident: Good",
            "Steering: Satisfactory",
            "Brakes: Satisfactory",
            # First format in the corpus to fill this field in.
            "Severity of impact: Medium",
            "Damage Areas: D right Hand rear · C right hand side · B right hand front",
            "Tyres- Depth (MM): Front Left Hand Inner 5mm · Front Right Hand "
            "Inner 5mm · Rear Left hand Inner 5mm · Rear Right Hand Inner 5mm",
            "Addresses — Insured: John Doe",
            'Note: "Using Manufacturer Times"',
        ],
    )

    add_page_break(doc)
    add_paragraphs(doc, header_lines)

    add_heading_line(doc, "Repair Information")
    add_heading_line(doc, "LABOUR")
    doc.add_paragraph("Time Basis 10 WU=1HR.Price £83.28/HR")
    labour_rows = [
        ["52904A", "REPAIR RR WINDOW REGULATOR", "10.0"],
        ["8652", "CORROSION PROTE TO 3 PANEL", "6.0"],
        ["8677 ZAX", "ADAS STATIS RESET", "32.0"],
        ["000", "HYBRID SHUT DOWN VEHICLE", "10.0"],
        ["100", "CHECK WATER TEST", "10.0"],
        ["8246R7", "REPAIR PULLING SIDE PANEL", "10.0"],
        ["5246R7B", "REPAIR RR SIDE PANEL", "15.0"],
        ["86246R7B", "REPAIR B PILLAR", "15.0"],
        ["99088A00", "REPAIR RF W ARCH MOULDING", "15.0"],
        ["991088A00", "REMOVE AND REFIT RELEASE REAR BUMPER", "3.0"],
        ["4556", "REMOVE AND REFIT RELEASE FRONT BUMPER", "3.0"],
        ["0281", "REMOVE AND REFIT R SILL FOIL", "2.0"],
        ["0291", "RR RIGHT REAR WHEEL", "1.0"],
        ["0300", "RR RIGHT REAR WHEELHOUSE SHELL", "1.0"],
        ["144", "WITH DOOR REMOVED", "0.0"],
        ["1425", "REPLACE HINGE LEAVES ON RH B PILLAR", "3.0"],
        ["1000", "RR RIGHT REAR LOCK STRIKER", "1.0"],
        ["1000", "RR DOOR MIRROR INDICATOR", "1.0"],
        ["1000", "RR OUTER MIRROR HOUSING", "1.0"],
        ["1000", "RR OUTER MIRROR", "1.0"],
        ["1000", "RR RIGHT REAR DOOR EDGE PROTECTION", "1.0"],
        ["1000", "RR RIGHT FRONT DOOR EDGE PROTECTION", "1.0"],
        ["1000", "RR SIDE PANEL PROTECTIVE MOULDING", "1.0"],
        ["1000", "ON OFF CHASSIS JIG", "15.0"],
        ["1000", "CHECK AND ROAD TEST STD", "3.0"],
        ["1000", "REPAIR R/DOOR LOWER", "40.0"],
        ["1000", "RR REAR MOULDING RIGHT REAR WHEELARCH", "2.0"],
        ["1000", "RR WHEELHOUSE MOULDING", "1.0"],
        ["1000", "RR LOWER DOOR MOULDING", "3.0"],
        ["1000", "RF LOWER DOOR MOULDING", "3.0"],
        ["1000", "RR OUTER REAR LAMP", "1.0"],
        ["1000", "CLEARANCES, SEAL", "0.0"],
        ["1000", "NECESSAY FIR HINGE", "0.0"],
        ["1000", "INCLUDES REFIT COMPONENTS PARTS", "0.0"],
        ["1000", "REPLACE RH REAR DOOR", "18.0"],
        ["1000", "RR RIGHT REAR DOOR CPL", "2.0"],
        ["1000", "RIGHT REAR DOOR EDGW SEALANT", "2.0"],
        ["1000", "RF OUTER DOOR CHANNEL MOULDING", "1.0"],
        ["1000", "RR ROGHT FRONT OUTER DOOR HANDLE", "1.0"],
        ["1000", "RF DOOR TRIM", "2.0"],
        ["1000", "RF WHEELARCF MOULD", "2.0"],
        ["1000", "ALIGN CPL BEFORE REPAIR", "8.0"],
        ["1000", "ADD TIME FOR ONE MAIN POSITION", "2.0"],
        ["", "Total Work Units", "244.0"],
        ["", "TOTAL PANEL/MECHANICAL LABOUR 24.4 HOURS", "£2032.03"],
    ]
    add_schedule_table(doc, ["Guide Number", "Description", "WU"], labour_rows)

    add_page_break(doc)
    add_paragraphs(doc, header_lines)

    add_heading_line(doc, "PAINT WORK")
    doc.add_paragraph("Time Basis 10 WU=1HR.Price £83.28/HR")
    paint_rows = [
        ["1000", "HINGE NEW PAINT", "8.0"],
        ["1000", "R DOOR LOWER REPAIR PAINT >50%", "26.0"],
        ["1000", "RR SIDE PANEL REPAIR PAINT <50%", "12.0"],
        ["1000", "RIGHT B PILLAR REPAIR PAINT <50%", "10.0"],
        ["1000", "R DOOR MIRROR HSG REPAIR PAINT PLASTIC", "9.0"],
        ["1000", "R/F DOOR HANDLE TRIM REPAIR PAINT", "9.0"],
        ["1000", "RF DOOR OUT HANDLE REPAIR PAINT", "9.0"],
        ["1000", "PREPARATION FOR PRE PAINT", "35.0"],
        ["1000", "DETAILED MASKING REPAIR", "3.0"],
        ["1000", "R ROOF FRAME SURFACE PAINT", "5.0"],
        ["1000", "R A PILLAR SURFACE PAINT", "4.0"],
        ["1000", "R OUTER SILL PANEL SURFACE PAINT", "5.0"],
        ["1000", "R/F WING SURFACE PAINT", "5.0"],
        ["1000", "RR DOOR NEW PART PAINT", "16.0"],
        ["", "Total Work Units", "156.0"],
        ["", "Total Paint Labour", "£1299.17"],
    ]
    add_schedule_table(doc, ["Number", "Description", "WU"], paint_rows)

    # As format 3, but this table's own rows actually add up to its final
    # line (format 3's did not).
    add_heading_line(doc, "Material cost paint")
    material_cost_paint_rows = [
        ["Total paint Cost", "1167.76"],
        ["Sundry Paint Material", "0.00"],
        ["Pre-Painting sundry materials", "257.96"],
        ["Total Excluding Pearlescent uplift", "1425.72"],
        ["Pearlescent Uplift", "0.00"],
        ["Discounted by", "0.00"],
        ["Total paint and Material cost", "1425.72"],
    ]
    add_schedule_table(doc, ["Line", "Value (£)"], material_cost_paint_rows)

    add_heading_line(doc, "PARTS")
    # No "Part Number" / "Bet." columns on this format's PARTS table --
    # just Guide No., Description, Price, unlike formats 1, 3 and 7.
    # The eleven rows sum to £995.39, but the printed SUB TOTAL is
    # £1005.39 -- £10.00 unaccounted, reproduced verbatim. A 9.00%
    # deduction rate is printed with a £0.00 amount.
    parts_rows = [
        ["1000", "RD MIRROR INDCATOR", "18.26"],
        ["1000", "RR DOOR", "632.00"],
        ["1000", "RR UPPER DOOR HINGE", "32.96"],
        ["1000", "RR LOWER DOOR HINGE", "46.85"],
        ["1000", "RR OUT WINDOW MOULD", "34.80"],
        ["1000", "RR DOOR MOULDING", "30.13"],
        ["1000", "RR OUT DOOR RR FOIL", "16.91"],
        ["1000", "RR OUT FRT FOIL", "13.92"],
        ["1000", "RR DOOR LWR MLD", "102.64"],
        ["1000", "RR DR FRAME RR TRI", "25.21"],
        ["1000", "RR W HOUSE MLD RR", "41.71"],
        ["", "SUB TOTAL", "1005.39"],
        ["", "DEDUCTION FROM RRP (9.00%)", "0.00"],
        ["", "SUNDRY PARTS", "99.00"],
        ["", "Total Parts", "1104.39"],
    ]
    add_schedule_table(doc, ["Guide No.", "Description", "Price"], parts_rows)

    add_heading_line(doc, "EXTRAS")
    # The descriptions for all but the first row were not captured in the
    # photographs (the Description column was blank or offset for most
    # rows) -- prices are kept in document order with the description cell
    # left empty rather than guessed.
    extras_rows = [
        ["ANTI CORROSION PROTE", "0%", "83.28"],
        ["", "", "249.84"],
        ["", "", "78.00"],
        ["", "", "83.28"],
        ["", "", "20.82"],
        ["", "", "41.00"],
        ["", "", "50.00"],
        ["", "", "41.64"],
        ["", "", "31.23"],
        ["", "", "26.00"],
        ["", "", "30.00"],
        ["", "", "83.28"],
        ["", "", "176.96"],
        ["Total Extras", "", "1089.02"],
    ]
    add_schedule_table(doc, ["Description", "Bet.", "Price"], extras_rows)

    add_page_break(doc)
    add_paragraphs(doc, header_lines)

    add_heading_line(doc, "Calculation")
    # Unlike format 3, this block's Total Parts agrees with the PARTS page.
    add_paragraphs(
        doc,
        [
            "Total Panel/Mechanical: £2032.03",
            "Total Paintwork: £1299.17",
            "Total Labour: £3331.20",
            "Total Paint/material cost: £1425.72",
            "Total Parts: £1104.39",
        ],
    )

    add_heading_line(doc, "Additional costs")
    # Cost of specialist is exactly Total Extras above -- EXTRAS is not a
    # separate addend, it flows into Additional costs.
    add_paragraphs(
        doc,
        [
            "Corrosion Protection Materials External: £72.00",
            "Cost of specialist: £1089.02",
            "Total Additional Cost: £1161.02",
        ],
    )

    add_heading_line(doc, "Subject to check")
    add_paragraphs(
        doc,
        [
            "Subject to check: £0.00",
            "Overall discount: £0.00",
            "Total Deductions: £0.00",
        ],
    )

    add_heading_line(doc, "Grand total")
    # "Grand Total Excl VAT" printed twice -- the second is Incl VAT. VAT
    # Status "Non Taxable" yet VAT is charged. Both reproduced verbatim.
    add_paragraphs(
        doc,
        [
            "Grand Total Excl VAT: £7022.33",
            "VAT at 20%: £1404.47",
            "Grand Total Excl VAT: £8426.80",
            "Excess: £0.00",
        ],
    )

    return doc


def build_invoice_4_request_for_payment() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "DL Assistance")
    add_paragraphs(doc, [DLAS_ISSUER_BLOCK, "** Request for Payment **"])
    add_paragraphs(
        doc,
        [
            "Invoice Date: 27/04/2026",
            # Identical to invoice 3's invoice number -- the second
            # duplicate-invoice-number pair in this corpus (formats 1 and 7
            # share the other one). Reproduced verbatim; never an identity
            # key.
            "Invoice Number: 132467/1~FT56678",
        ],
    )

    add_grid_table(
        doc,
        [
            ("Reference Name", "John Doe", "Vehicle Registration", "PD73UUF"),
            ("Claim No", "1111111/1", "Vehicle Make", "FORD"),
            ("Policy No", "9865433", "Vehicle Model", "Puma"),
            ("Assessment Ref", "Y5657687", "Excess", "£0.00"),
            ("Collection Date", "24/04/2026", "Insured VAT Status", "Non Taxable"),
        ],
    )

    body_rows = [
        ["Total Parts Amount", "1104.39", "220.88"],
        ["Total Paint & Materials Amount", "1425.72", "285.14"],
        ["Total Labour Amount", "3331.20", "666.24"],
        ["Total", "5861.31", "1172.26"],
        ["Additional charges", "1161.02", "232.20"],
        ["Deductions", "0.00", "0.00"],
        ["Total Sum Equivalent to VAT @20%", "1404.47", ""],
        ["Invoice Total", "8426.80", ""],
        ["Policy Excess Paid by Customer-", "0.00", ""],
        ["Total Due", "8426.80", ""],
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
    add_paragraphs(
        doc,
        [
            "Invoice Date: 2/3/2023",
            # Same invoice number as pair 1's invoice, despite a different
            # claim -- the client's own duplicate, reproduced verbatim.
            "Invoice Number: 343653726836/1~3538",
            "DL Claim number: 426953180/3",
            "DL policyholder: Oliver Reed",
            "Vehicle Registration : JK21MNO",
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
# Formats 5 and 6 -- the format 1 family's other two members.
#
# Both reports print the same 25-row LABOUR list and the same 16-row PAINT
# WORK list as format 1, under different identities and at different prices
# (client-formats/2026-09-16_dl-auda-format-{5,6}-engineer-report/). The two
# lists are named here rather than retyped per builder; format 1's own
# builder above keeps its inline copies untouched so its bytes cannot move.
# --------------------------------------------------------------------------

#: 25 operations summing to 101 WU, under a printed total of 218 -- the
#: client's own discrepancy, carried identically by formats 1, 5 and 6.
FAMILY_LABOUR_ROWS: list[list[str]] = [
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
    ["", "Total Work Units", "218"],
]

#: 16 paint operations summing to 151 WU against a printed 151.0 -- exact.
FAMILY_PAINT_ROWS: list[list[str]] = [
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

#: The Model Options free-text column formats 1, 5 and 6 all print.
FAMILY_MODEL_OPTIONS = (
    "FROM 06/2017 · MODEL i30 · HEAT ABSORBING GLASS · WITH A/C · "
    "DRIVER SEAT HEIGHT · WITHOUT ALARM · ELECTRIC FOLDING MIRROR · "
    "HEATED WINDSCREEN · FRONT / REAR PARKING SENSOR · REAR CAMERA · "
    "STEERING WHEEL CONTROLS · START / STOP SYSTEM · CRUISE CONTROL · "
    "DOOR COVERS · TIRE REPAIR KIT · DIMENSION 570 R/O · BASECOAT CLEAR"
)


def build_auda_format_5_assessment() -> DocxDocumentType:
    doc = _new_document()

    # Page-1 banner carries L0987892222 -- the same outlier format 1 prints --
    # while the Summary grid and every later page header agree on D8432196.
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
            ("Assessment Number", "D8432196", "Reference Name", "Alex Turner"),
            ("First Received", "12/11/2025", "Assigned to", "DL"),
            ("Assessment Status", "Active", "Auth/total loss date", ""),
            ("Authorization Status", "Authorized", "Date of accident", "30/12/2025"),
            ("Work Provider", "DL- Marvin", "Excess", "£0.00"),
            ("Claim Reference", "247816542/1", "Able to authorize repairs", "Yes"),
            ("Policy Number", "PX-784219", "Are the repairs authorized", "Yes"),
            ("Other reference", "", "Date of inspection", ""),
            ("Version", "TRN-02/1", "Place of inspection", "Repairer"),
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
            "Registration Number: CD34EFG",
            "VIN Number: TRN9876543210",
            "Registration Month: march",
            "Registration Year: 2018",
            "Odometer: 576882 miles",
        ],
    )

    add_heading_line(doc, "Model Options")
    add_paragraphs(doc, [item.strip() for item in FAMILY_MODEL_OPTIONS.split("·")])

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
            "Addresses — Insured: Alex Turner",
            'Note: "Using Manufacturer Times"',
        ],
    )

    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Assessment Number: D8432196",
            "Version: TRN-02/1",
            "Full report",
            "Printed: 11/09/2026",
        ],
    )

    add_heading_line(doc, "Repair Information")
    add_heading_line(doc, "LABOUR")
    doc.add_paragraph("Time Basis 10 WU=1HR.")
    add_schedule_table(doc, ["Number", "Description", "WU"], FAMILY_LABOUR_ROWS)

    add_heading_line(doc, "PAINT WORK")
    doc.add_paragraph("Time Basis 10 WU=1HR.")
    add_schedule_table(doc, ["Number", "Description", "WU"], FAMILY_PAINT_ROWS)

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
        # Internally perfect -- and contradicted by the Summary page's
        # Total Parts of 1308.46 further down, which is what the printed
        # grand total is actually built on.
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
        # Rows sum to 136.50; the printed total is 136.32 (an 18p gap), and
        # the Summary page states a different figure again (144.13).
        ["Total Extras", "", "136.32"],
    ]
    add_schedule_table(doc, ["Description", "Bet.", "Price"], extras_rows)
    doc.add_paragraph("Claims Details")

    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Assessment Number: D8432196",
            "Version: TRN-02/1",
            "Full report",
            "Printed: 11/09/2026",
        ],
    )

    add_heading_line(doc, "Calculation")
    add_paragraphs(
        doc,
        [
            # 218 WU = 21.8h and 151 WU = 15.1h both price out at ~£71.90/HR,
            # so neither printed rate reproduces either total.
            "Labour Rate: £38.00",
            "Paint Rate: £68.00",
            "Paint Index: 100.00%",
            "Parts Discount: 0.00%",
            "Overall Discount: 0.00%",
            "Labour — Total Panel/mechanical: £1567.36",
            "Labour — Total Paintwork: £1085.65",
            "Total Labour: £2653.01",
        ],
    )

    add_heading_line(doc, "Summary")
    add_paragraphs(
        doc,
        [
            "Total Paint / Materials Costs: 1088.59",
            "Total Parts: 1308.46",
            "Total Additional Costs: 144.13",
            "Overall Discount: 0.00",
            "Repair Grand Total Excl. VAT: 5194.19",
            "Grand Total Excl. VAT: 5194.19",
            "VAT 20%: 1038.84",
            "Grand Total Incl. VAT: 6233.03",
            "Total Due: 6233.03",
        ],
    )

    return doc


def build_repair_invoice_format_5() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "DLAS")
    add_paragraphs(doc, [DLAS_ISSUER_BLOCK, "INVOICE"])
    add_paragraphs(
        doc,
        [
            "Invoice Date: 2/3/2023",
            # The third document in the corpus to print this invoice number.
            "Invoice Number: 343653726836/1~3538",
            "DL Claim number: 247816542/1",
            "DL policyholder: Alex Turner",
            "Vehicle Registration : CD34EFG",
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
        ["Cavity Wax Remover", "6.75"],
        ["Car Care Kit", "8.00"],
        ["E.P.A. Charge", "22.00"],
        ["Tech Data + Methods", "38.00"],
        ["Total", "136.32"],
    ]
    add_schedule_table(doc, ["Specialist Operation", "Cost (£)"], specialist_rows)

    add_paragraphs(
        doc,
        [
            # The invoice's own printed lines add to 5115.42, but the VAT is
            # 20% of the *report's* 5194.19 and the total follows it: the
            # £78.77 gap is parts (1308.46 - 1237.50 = 70.96) plus additional
            # (144.13 - 136.32 = 7.81). Reproduced exactly; never reconciled.
            "Total Labour: 2653.01",
            "Total Paint & materials: 1088.59",
            "An amount equivalent to VAT @20%: 1038.84",
            "Invoice total: 6233.03",
            "Total Due: 6233.03",
        ],
    )

    # The note asserts a reconciliation the printed lines do not support --
    # it even cites Total Additional Costs £144.13 while the Specialist
    # Operation block above it totals £136.32. Prose, not evidence.
    doc.add_paragraph(
        "Validation note: Updated against Assessment D8432196 / Claim "
        "Reference 247816542/1 for Alex Turner. Totals aligned to report: "
        "Total Parts £1,237.50; Total Additional Costs £144.13; Total "
        "Labour £2,653.01; Total Paint / Materials Costs £1,088.59; VAT "
        "£1,038.84; Total Due £6,233.03."
    )

    add_paragraphs(doc, [INVOICE_TERMS, REPAIRER_FOOTER])
    return doc


def build_auda_format_6_assessment() -> DocxDocumentType:
    doc = _new_document()

    # Unlike formats 1, 3, 5 and 7 the assessment number does not change
    # between page groups; only the page-1 Version is blank.
    add_heading_line(doc, "Assessment report")
    add_paragraphs(
        doc,
        [
            "Assessment Number: R6725148",
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
            ("Assessment Number", "R6725148", "Reference Name", "Maya Collins"),
            ("First Received", "12/11/2025", "Assigned to", "DL"),
            ("Assessment Status", "Active", "Auth/total loss date", ""),
            ("Authorization Status", "Authorized", "Date of accident", "30/12/2025"),
            ("Work Provider", "DL- Marvin", "Excess", "£0.00"),
            # The corpus's first "/2" suffix: it must never collide with a
            # hypothetical 318742905/1.
            ("Claim Reference", "318742905/2", "Able to authorize repairs", "Yes"),
            ("Policy Number", "PK-562847", "Are the repairs authorized", "Yes"),
            ("Other reference", "", "Date of inspection", ""),
            ("Version", "TRN-03/1", "Place of inspection", "Repairer"),
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
            "Registration Number: GH58JKL",
            "VIN Number: TRN5647382910",
            "Registration Month: march",
            "Registration Year: 2018",
            "Odometer: 576882 miles",
            # Column collapse visible in the source document itself: a Model
            # Options item printed in the left column directly under a
            # label/value line. An unlabelled line after a field is not that
            # field's continuation.
            "HEATED WINDSCREEN",
        ],
    )

    add_heading_line(doc, "Model Options")
    add_paragraphs(doc, [item.strip() for item in FAMILY_MODEL_OPTIONS.split("·")])

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
            "Addresses — Insured: Maya Collins",
            'Note: "Using Manufacturer Times"',
        ],
    )

    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Assessment Number: R6725148",
            "Version: TRN-03/1",
            "Full report",
            "Printed: 11/09/2026",
        ],
    )

    add_heading_line(doc, "Repair Information")
    add_heading_line(doc, "LABOUR")
    doc.add_paragraph("Time Basis 10 WU=1HR.")
    add_schedule_table(doc, ["Number", "Description", "WU"], FAMILY_LABOUR_ROWS)

    add_heading_line(doc, "PAINT WORK")
    doc.add_paragraph("Time Basis 10 WU=1HR.")
    add_schedule_table(doc, ["Number", "Description", "WU"], FAMILY_PAINT_ROWS)

    add_heading_line(doc, "PARTS")
    parts_rows = [
        ["1781", "L/R DOOR", "7700332300", "0%", "882.30"],
        ["2185", "L/SILL PANEL COVER", "8775132000", "0%", "330.22"],
        ["1000", "DOOR FITTING KIT", "Renew", "0%", "10.41"],
        ["1000", "SOUND PAD X1", "Renew", "0%", "3.54"],
        ["1000", "DOOR FOIL X1", "Renew", "0%", "4.16"],
        ["1000", "DOOR FITTING KIT", "Renew", "0%", "10.41"],
        ["1000", "LIGHT MOULDING CLIP", "Renew", "0%", "3.37"],
        ["", "", "", "Sub Total", "1,244.41"],
        ["", "", "", "Deduction from RRP", "-"],
        # 3.50% of 1,244.41 is 43.55; the source prints 43.53 on both the
        # report and the invoice, so the 2p is the document's, not ours.
        ["", "", "", "Sundry Parts", "43.53"],
        ["", "", "", "Total Parts", "1,287.94"],
    ]
    add_schedule_table(
        doc, ["Guide No.", "Description", "Part Number", "Betterment", "Price"], parts_rows
    )

    add_heading_line(doc, "EXTRAS")
    extras_rows = [
        ["Corrosion protection", "", "6.24"],
        ["Car Sanitisation", "", "31.22"],
        ["C/Car Class A", "", "0.00"],
        ["Fade Out Thinners", "", "3.64"],
        ["Seam Sealer", "", "3.64"],
        ["Panel Sundries", "", "5.20"],
        ["Body Filler", "", "10.41"],
        ["Lifting Tape", "", "3.90"],
        ["Cavity Wax Remover", "", "7.03"],
        ["Car Care Kit", "", "8.33"],
        ["EPA charge", "", "22.90"],
        ["Tech Data + Methods", "", "39.49"],
        # Rows sum to 142.00 against a printed 141.87 -- a 13p gap.
        ["Total Extras", "", "141.87"],
    ]
    add_schedule_table(doc, ["Description", "Bet.", "Price"], extras_rows)
    doc.add_paragraph("Claims Details")

    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            "Assessment Number: R6725148",
            "Version: TRN-03/1",
            "Full report",
            "Printed: 11/09/2026",
        ],
    )

    add_heading_line(doc, "Calculation")
    add_paragraphs(
        doc,
        [
            # Both sections imply ~£70.77/HR; the printed rates are decorative.
            "Labour Rate: £38.00",
            "Paint Rate: £68.00",
            "Paint Index: 100.00%",
            "Parts Discount: 0.00%",
            "Overall Discount: 0.00%",
            "Total Panel/mechanical: £1542.79",
            "Total Paintwork: £1068.62",
            "Total Labour: £2611.41",
        ],
    )

    add_heading_line(doc, "Summary")
    add_paragraphs(
        doc,
        [
            # Every one of these agrees with the page it came from: Total
            # Parts equals the PARTS page and Total Additional Costs equals
            # Total Extras. This is the document format 5 fails to be.
            "Total Labour: 2611.41",
            "Total Paint / Materials Costs: 1071.52",
            "Total Parts: 1287.94",
            "Total Additional Costs: 141.87",
            "Overall Discount: 0.00",
            "Repair Grand Total Excl. VAT: 5112.74",
            "Grand Total Excl. VAT: 5112.74",
            "VAT 20%: 1022.55",
            "Grand Total Incl. VAT: 6135.29",
            "Total Due: 6135.29",
        ],
    )

    return doc


def build_repair_invoice_format_6() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "DLAS")
    add_paragraphs(doc, [DLAS_ISSUER_BLOCK, "INVOICE"])
    add_paragraphs(
        doc,
        [
            "Invoice Date: 2/3/2023",
            # The fourth document sharing this invoice number.
            "Invoice Number: 343653726836/1~3538",
            "DL Claim number: 318742905/2",
            "DL policyholder: Maya Collins",
            "Vehicle Registration : GH58JKL",
        ],
    )

    add_heading_line(doc, "Parts")
    parts_rows = [
        ["1", "L/R DOOR 1781", "7700332300", "882.30", "882.30"],
        ["1", "L/SILL PANEL COVER 2185", "8775132000", "330.22", "330.22"],
        ["1", "Door Fitting Kit 1000", "Renew", "10.41", "10.41"],
        ["1", "DOOR FOIL X1 1000", "Renew", "4.16", "4.16"],
        ["1", "SOUND PAD X1 1000", "Renew", "3.54", "3.54"],
        ["1", "Door Fitting Kit 1000", "Renew", "10.41", "10.41"],
        ["1", "Light Moulding Clip 1000", "Renew", "3.37", "3.37"],
        ["", "Sundry parts", "3.50%", "", "43.53"],
        ["", "Total Parts", "", "", "1287.94"],
    ]
    add_schedule_table(
        doc, ["Qty", "Description", "Part Number", "Each", "Extended"], parts_rows
    )

    add_heading_line(doc, "Specialist Operation")
    specialist_rows = [
        ["Corrosion protection", "6.24"],
        ["Car Sanitisation", "31.22"],
        ["C/Car Class A", "0.00"],
        ["Fade Out Thinners", "3.64"],
        ["Seam Sealer", "3.64"],
        ["Panel Sundries", "5.20"],
        ["Body Filler", "10.41"],
        ["Lifting Tape", "3.90"],
        ["Cavity Wax Remover", "7.03"],
        ["Car Care Kit", "8.33"],
        ["E.P.A. Charge", "22.90"],
        ["Tech Data + Methods", "39.49"],
        ["Total", "141.87"],
    ]
    add_schedule_table(doc, ["Specialist Operation", "Cost (£)"], specialist_rows)

    add_paragraphs(
        doc,
        [
            # 1287.94 + 141.87 + 2611.41 + 1071.52 = 5112.74; VAT is 20% of
            # that and the total follows. Every figure agrees with the report.
            "Total Labour: 2611.41",
            "Total Paint & materials: 1071.52",
            "An amount equivalent to VAT @20%: 1022.55",
            "Invoice total: 6135.29",
            "Total Due: 6135.29",
        ],
    )

    # The same kind of note invoice 5 carries -- and here every claim in it
    # is true. Two notes asserting the same thing, one document wrong: the
    # note can never be the evidence.
    doc.add_paragraph(
        "Validation note: Updated against Assessment R6725148 / Claim "
        "Reference 318742905/2 for Maya Collins. Breakups aligned to report: "
        "Parts line items total £1,244.41 plus Sundry Parts £43.53 = Total "
        "Parts £1,287.94; Total Additional Costs £141.87; Total Labour "
        "£2,611.41; Total Paint / Materials Costs £1,071.52; VAT £1,022.55; "
        "Total Due £6,135.29."
    )

    add_paragraphs(doc, [INVOICE_TERMS, REPAIRER_FOOTER])
    return doc


# --------------------------------------------------------------------------
# The EXL demo pair -- a GT Motive-style engineer report and the corpus's
# third invoice layout
# (client-formats/2026-09-15_auda-2-engineer-report/). This is the pair the
# client demos with, and nothing else in the corpus resembles the invoice:
# a bordered two-column label/value table, a rolled-up summary with no line
# items, the repairer named only in the page-2 footer, the only VAT
# registration number in the corpus, and a grand total labelled "Claim".
#
# The invoice's layout is transcribed in full. The report's photographs
# record its field values but not whether each is printed as a grid cell or
# as "Label: value", so it is built with the "Label: value" paragraphs the
# rest of the corpus's reports use for their Vehicle Details blocks.
# --------------------------------------------------------------------------

EXL_INSURER_BLOCK = (
    "EXL Insurance Company Ltd, St Clare House, 30-33 Minories, London, EC3N 1DD"
)
EXL_REPAIRER_FOOTER = (
    "EXL Repairer Services Ltd, Registered Office: PO Box 1122, County Gate, "
    "London, AB1 9ZE"
)


def add_label_value_table(doc: DocxDocumentType, rows: list[tuple[str, str]]) -> DocxTable:
    """Bordered two-column `Label | Value` table, no colons (EXL invoice)."""

    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value
    return table


def build_exl_demo_engineer_report() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "Engineer Report")
    add_paragraphs(
        doc,
        [
            # Printed with an "ABC " prefix the matching invoice does not
            # carry: the invoice's Claim Reference is a bare "123456".
            "Claim: ABC 123456",
            "Company: EXL MANAGEMENT SOLUTIONS LTD",
            "Work Provider: Other 000",
            "Policy Number: 200-1222-33333",
            "Accident Date: 13/01/2026",
            "Inspection: Onsite Inspection Vehicle Inspection",
            "Excess: £0.00",
            "EXL MANAGEMENT SOLUTIONS LTD, St Clare House, 30-33 Minories, "
            "London, EC3N 1DD",
            "Insured address:",
        ],
    )

    add_heading_line(doc, "Estimate details")
    add_paragraphs(
        doc,
        [
            "Estimate ID: AAA6576879",
            "Estimate Version: 0",
            "Estimate Status: Authorised",
            "Estimate Date: 25/01/2026",
        ],
    )

    add_heading_line(doc, "Vehicle details")
    add_paragraphs(
        doc,
        [
            "Make: VOLVO",
            # Brackets and a trailing hyphen: free text, never shape-checked.
            "Model: XC40(XZ)(18-)",
            # Eight characters and not a standard UK plate shape.
            "Reg. No: ABC02QQQ",
            "VIN: Xy4AAA565T686T8",
            "Mileage: 80,25",
            "Registration Date: 31/05/2025",
            "Colour: Light Green",
            "Manufacturer Colour Code:",
        ],
    )

    add_heading_line(doc, "Equipment")
    equipment = (
        "FRONT/REAR PARKING ASSIST SYSTEM SEMI-AUTOMATIC WITH BRAKINGS · 5 DOORS · "
        "VARIANT CODE · BODYWORK COLOUR · REAR WING MOLDING RECHARGE · "
        "TARFFIC ON THE LEFT · VEHICLE WITH RIGHT HAND STEERING WHEEL · "
        "MILS INSPECTION SERVICE · 1922CC 120KW(180) · "
        "WITHOUT ERAD ELECTRIC ENGINE 54KW · "
        "WITHOUT 48V KERS HYBRID ASSISTANCE SYSTEM · PETROL ENGINE · "
        "ENGINE 4 CYLINDERS · FUEL PROPULSION SYSTEM · UNITED KINGDOM · "
        "RANGE 2025 · LUQIAO ASSEMBLT PLANT · VARIANT CODE"
    )
    add_paragraphs(doc, [item.strip() for item in equipment.split("·")])

    add_page_break(doc)
    add_heading_line(doc, "Repair Details")
    add_heading_line(doc, "Parts")
    add_schedule_table(
        doc,
        ["Code", "Description", "Units", "Price", "Total"],
        [
            ["Replace", "Replace-i/h/r wing moulding", "1.00", "60.00", "60.00"],
            ["Replace", "Replace- l/h/r tyre", "1.00", "241.88", "241.88"],
            ["578675", "Rear bumper", "1.00", "541.00", "541.00"],
            ["SMA01", "Sundry parts", "1.00", "29.50", "29.50"],
            ["", "Total", "", "", "872.38"],
        ],
    )

    add_heading_line(doc, "Labour")
    add_schedule_table(
        doc,
        ["Code", "Description", "Units"],
        [
            ["CTC1000", "Check VEHICLE SHUTDOWN", "1.00"],
            ["CTC1000", "Check PRE REPAIR CLEANING CHARGE", "0.50"],
            ["CTC1000", "Check MACHINE POLISH", "0.30"],
            ["1111-2", "Remove and refit Left rear tail light", "0.50"],
            ["Gtr55t6", "Repair Rear bumper(left area)", "1.00"],
            ["Gtr55t6", "Repair rear left wing", "0.50"],
            ["Gr787889890909090", "Check BASIC CLEAN", "1.00"],
            ["Gr787889890909090", "Check Pre-REPAIR CLEAN", "0.50"],
            [
                "Gr787889890909090",
                "Check ROAD TEST AND FINAL QUALITY INSPECTION",
                "1.00",
            ],
            [
                "Gr787889890909090",
                "CHECK SYSTEM DIAGNOSTIC CHECK POST SWEEP",
                "1.00",
            ],
            ["Gr787889890909090", "CHECK SYSTEM DIAGNOSTIC CHECK PRE SWEEP", "1.00"],
            ["Gr787889890909090", "CHECK TYRE/WHEEL CHANGE", "0.50"],
            ["Gr787889890909090", "CHECK TRIAL PANEL FIT", "0.50"],
            ["Gr787889890909090", "CHECK ELECTRIC/HYBRID SHUT DOWN", "2.00"],
            ["Gr787889890909090", "CHECK ELECTRIC/HYBRID RISK ASSESMENT", "0.50"],
            ["353427", "Replace Rear bumper", "1.40"],
            [
                "Gr787889890909090",
                "Anti-corrosion Treatment ANTI CORROSION LABOUR-1 PANEL",
                "0.30",
            ],
            ["Gh6687", "Remove and refit R+R", "0.30"],
            ["GrReplace", "Replace replace", "0.00"],
            ["", "Total Labour hours", "13.80 h"],
            # The £104.55/h this implies is printed nowhere.
            ["", "Total", "£1442.84"],
        ],
    )

    add_heading_line(doc, "Paint Labour")
    add_schedule_table(
        doc,
        ["Code", "Description", "Units"],
        [
            ["DGHJ797", "Rear bumper (left area) Repaired (K3) Parts removed", "1.00"],
            ["DGHJ797", "Rear left wing Repaired <50% (III)", "1.50"],
            ["GH79778", "Preparation paintwork", "3.10"],
            ["", "Total Labour Hours", "5.60 h"],
            ["", "Total", "£577.14"],
        ],
    )

    add_heading_line(doc, "Paint and Materials")
    add_schedule_table(
        doc,
        ["Code", "Description", "Units", "Price", "Total"],
        [
            [
                "DGHJ797",
                "Rear bumper (left area) Repaired (K3) Parts removed",
                "1.00",
                "63.26",
                "63.26",
            ],
            ["DGHJ797", "Rear left wing Repaired <50% (III)", "1.00", "155.60", "155.60"],
            ["GH79778", "Preparation paintwork", "1.00", "165.19", "165.19"],
            ["", "Pearlescent Uplift", "1.00", "5.76", "5.76"],
            ["", "Total", "", "", "389.81"],
        ],
    )

    add_page_break(doc)
    add_heading_line(doc, "Additional Items")
    add_schedule_table(
        doc,
        ["Code", "Description", "Total"],
        [
            ["Gr787889890909090", "Specialist ANTI CORROSION TO 1ST PANEL", "15.61"],
            ["Gr787889890909090", "Specialist BS586687 COMPLIANCE", "41.64"],
            ["Gr787889890909090", "Specialist CAR CARE KIT", "10.41"],
            ["Gr787889890909090", "Specialist COLLECTION FEE", "78.07"],
            ["Gr787889890909090", "Engineers Fee", "31.23"],
            ["Gr787889890909090", "Specialist ELECTRIC VEHICLE FULL RECHARGE", "52.05"],
            [
                "Gr787889890909090",
                "Specialist ENVIRONMENTAL INVESTMENT AND SUSTAINABLITY CHARGE",
                "25.00",
            ],
            [
                "Gr787889890909090",
                "Specialist FEE FOR COMPILATION OF ASSESMNET BY REPAIRER",
                "176.96",
            ],
            ["Gr787889890909090", "Specialist PANEL REPAIR SUNDRIES", "26.02"],
            [
                "Gr787889890909090",
                "Specialist PERSONAL BELONGINGS CHECK AND REMOVAL",
                "30.00",
            ],
            ["Gr787889890909090", "Specialist RETURN OF REPAIRED VEHICLE", "78.07"],
            ["Gr787889890909090", "Specialist STEERING CHECK ONLY", "174.88"],
            ["Gr787889890909090", "Specialist TYRE DISPOSAL", "5.21"],
            ["Gr787889890909090", "Specialist WHEEL REFURBISMENT DIAMOND CUT", "196.74"],
            ["", "Additional Total Items", "941.89"],
        ],
    )

    add_heading_line(doc, "Summary Calculation")
    add_paragraphs(
        doc,
        [
            "Parts Total: 872.38",
            "Total Labour (Met & Pnt): 1,442.84",
            "Total Labour (Paint): 577.14",
            "Total Labour: 2,019.98",
            "Total Paint and Materials: 389.81",
            "Additional Items: 941.89",
            "Subtotal: 4,224.06",
            "Sum Equivalent to VAT @20%: 844.81",
            "Grand Total: 5,068.87",
            "Total Disbursements: 0.00",
            "Excess: 0.00",
            "Total Due: 5,068.87",
        ],
    )
    doc.add_paragraph("GT Motive, A.A 03/03/2026 — 1/3")

    return doc


def build_exl_demo_invoice() -> DocxDocumentType:
    doc = _new_document()

    add_heading_line(doc, "Invoice")
    # The top of this document names the party being billed, not the
    # repairer -- the inverse of the DLAS invoices. The repairer is the
    # page-2 footer company, as it is there.
    add_paragraphs(doc, ["Bill To", EXL_INSURER_BLOCK])

    add_label_value_table(
        doc,
        [
            ("Invoice Number", "ABC1234"),
            ("Invoice Date", "25/02/2026"),
            ("Insured Name", "John Smith"),
            # No "/n" suffix, against format 2's "123456/1". Two different
            # claims separated only by the suffix; they must never collide.
            ("Claim Reference", "123456"),
            # Lower-case "r", against the DLAS "Vehicle Registration".
            ("Vehicle registration", "ABC02QQQ"),
            ("Vehicle Make", "VOLVO"),
            ("Vehicle Model", "XC40(XZ)(18-)"),
        ],
    )

    # Fully rolled up: six amounts, no line items, and a grand total labelled
    # "Claim" -- no "Total", "Grand Total", "Invoice Total" or "Total Due"
    # appears anywhere on this document. "Collection & Delivery" and
    # "Recovery" are line-item types nothing else in the corpus prints, and
    # Recovery is genuinely blank (the arithmetic confirms the alignment).
    add_schedule_table(
        doc,
        ["Summary", "Amount (£)"],
        [
            ["Labour", "2019.98"],
            ["Parts", "872.38"],
            ["Paint", "389.81"],
            ["Additional Extras", "785.75"],
            ["Collection & Delivery", "156.14"],
            ["Recovery", ""],
            ["VAT", "844.81"],
            ["Claim", "5068.87"],
        ],
    )

    add_page_break(doc)
    add_paragraphs(
        doc,
        [
            EXL_REPAIRER_FOOTER,
            # "Cose" is the source's own typo for "Code".
            "Remit to Sort Cose: 111111, Account No: 33366888",
            # The only VAT registration number in the corpus.
            "VAT Registration no. 106 9411 33",
            "Company Reg no 0987654",
        ],
    )
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
        "filename": "DL_Auda_format_3_assessment.docx",
        "document_kind": "engineer_assessment",
        "pair_id": 3,
        "claim_reference": "354647/1",
        "policy_number": "103466899",
        "registration": "AM06TAH",
        "vehicle_make": "SEAT",
        "vehicle_model": "IBIZA",
        "assessment_number": "D38892111",
        "assessment_ref": None,
        "invoice_number": None,
        "section_totals": {
            "labour": "1598.97",
            "paint_materials": "384.18",
            "parts": "13.56",
            "extras": "4.00",
            "additional": "4.00",
        },
        "gross_total": "2400.85",
    },
    {
        "filename": "DL_Invoice_3_request_for_payment.docx",
        "document_kind": "repair_invoice",
        "pair_id": 3,
        "claim_reference": "354647/1",
        "policy_number": "103466899",
        "registration": "AM06TAH",
        "vehicle_make": "SEAT",
        "vehicle_model": "IBIZA",
        "assessment_number": None,
        "assessment_ref": "I535377",
        "invoice_number": "132467/1~FT56678",
        "section_totals": {
            "parts": "13.56",
            "paint_materials": "384.18",
            "labour": "1598.97",
            "additional": "4.00",
        },
        "gross_total": "2400.85",
    },
    {
        "filename": "DL_Auda_format_4_assessment.docx",
        "document_kind": "engineer_assessment",
        "pair_id": 4,
        "claim_reference": "1111111/1",
        "policy_number": "9865433",
        "registration": "PD73UUF",
        "vehicle_make": "FORD",
        "vehicle_model": "Puma",
        "assessment_number": "D067789900",
        "assessment_ref": None,
        "invoice_number": None,
        "section_totals": {
            "labour": "3331.20",
            "paint_materials": "1425.72",
            "parts": "1104.39",
            "extras": "1089.02",
            "additional": "1161.02",
        },
        "gross_total": "8426.80",
    },
    {
        "filename": "DL_Invoice_4_request_for_payment.docx",
        "document_kind": "repair_invoice",
        "pair_id": 4,
        "claim_reference": "1111111/1",
        "policy_number": "9865433",
        "registration": "PD73UUF",
        "vehicle_make": "FORD",
        "vehicle_model": "Puma",
        "assessment_number": None,
        "assessment_ref": "Y5657687",
        "invoice_number": "132467/1~FT56678",
        "section_totals": {
            "parts": "1104.39",
            "paint_materials": "1425.72",
            "labour": "3331.20",
            "additional": "1161.02",
        },
        "gross_total": "8426.80",
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
    {
        "filename": "DL_Auda_format_5_assessment.docx",
        "document_kind": "engineer_assessment",
        "pair_id": 5,
        "claim_reference": "247816542/1",
        "policy_number": "PX-784219",
        "registration": "CD34EFG",
        "vehicle_make": "HYUNDAI",
        "vehicle_model": "140 SE Nav",
        "assessment_number": "D8432196",
        "assessment_ref": None,
        "invoice_number": None,
        "section_totals": {
            "labour": "2653.01",
            "paint_materials": "1088.59",
            # The PARTS and EXTRAS pages, as every other entry here records.
            "parts": "1237.50",
            "extras": "136.32",
            # ...and the Summary page, which disagrees with both and is what
            # the printed grand total is actually built on: 2653.01 +
            # 1088.59 + 1308.46 + 144.13 = 5194.19. The gaps are 70.96 and
            # 7.81 -- together the £78.77 the matching invoice bills short.
            "parts_summary_page": "1308.46",
            "extras_summary_page": "144.13",
        },
        "gross_total": "6233.03",
    },
    {
        "filename": "DL_Repair_Invoice_format_5.docx",
        "document_kind": "repair_invoice",
        "pair_id": 5,
        "claim_reference": "247816542/1",
        "policy_number": None,
        "registration": "CD34EFG",
        "vehicle_make": None,
        "vehicle_model": None,
        "assessment_number": None,
        "validation_note_assessment_number": "D8432196",
        "assessment_ref": None,
        "invoice_number": "343653726836/1~3538",
        "section_totals": {
            "parts": "1237.50",
            "extras": "136.32",
            "labour": "2653.01",
            "paint_materials": "1088.59",
        },
        "gross_total": "6233.03",
    },
    {
        "filename": "DL_Auda_format_6_assessment.docx",
        "document_kind": "engineer_assessment",
        "pair_id": 6,
        "claim_reference": "318742905/2",
        "policy_number": "PK-562847",
        "registration": "GH58JKL",
        "vehicle_make": "HYUNDAI",
        "vehicle_model": "140 SE Nav",
        "assessment_number": "R6725148",
        "assessment_ref": None,
        "invoice_number": None,
        "section_totals": {
            "labour": "2611.41",
            "paint_materials": "1071.52",
            "parts": "1287.94",
            "extras": "141.87",
        },
        "gross_total": "6135.29",
    },
    {
        "filename": "DL_Repair_Invoice_format_6.docx",
        "document_kind": "repair_invoice",
        "pair_id": 6,
        "claim_reference": "318742905/2",
        "policy_number": None,
        "registration": "GH58JKL",
        "vehicle_make": None,
        "vehicle_model": None,
        "assessment_number": None,
        "validation_note_assessment_number": "R6725148",
        "assessment_ref": None,
        "invoice_number": "343653726836/1~3538",
        "section_totals": {
            "parts": "1287.94",
            "extras": "141.87",
            "labour": "2611.41",
            "paint_materials": "1071.52",
        },
        "gross_total": "6135.29",
    },
    {
        "filename": "EXL_demo_engineer_report.docx",
        "document_kind": "engineer_assessment",
        "pair_id": 8,
        # Printed "ABC 123456"; the matching invoice prints a bare "123456".
        "claim_reference": "ABC 123456",
        "policy_number": "200-1222-33333",
        "registration": "ABC02QQQ",
        "vehicle_make": "VOLVO",
        "vehicle_model": "XC40(XZ)(18-)",
        "assessment_number": "AAA6576879",
        "assessment_ref": None,
        "invoice_number": None,
        "section_totals": {
            "labour": "2019.98",
            "paint_materials": "389.81",
            "parts": "872.38",
            "extras": "941.89",
        },
        "gross_total": "5068.87",
    },
    {
        "filename": "EXL_demo_invoice.docx",
        "document_kind": "repair_invoice",
        "pair_id": 8,
        # No "/n" suffix, and it must never collide with format 2's
        # "123456/1".
        "claim_reference": "123456",
        "policy_number": None,
        "registration": "ABC02QQQ",
        "vehicle_make": "VOLVO",
        "vehicle_model": "XC40(XZ)(18-)",
        "assessment_number": None,
        "assessment_ref": None,
        "invoice_number": "ABC1234",
        "supplier_vat_number": "106 9411 33",
        "section_totals": {
            # Printed bare: "Labour", "Parts", "Paint", "Additional Extras".
            "labour": "2019.98",
            "parts": "872.38",
            "paint_materials": "389.81",
            "extras": "785.75",
            # No line_item_type in the domain covers either of these; they
            # are printed section labels nothing else in the corpus carries.
            # "Recovery" is printed with a blank amount (the arithmetic
            # confirms it, so the rows are not offset by one).
            "collection_and_delivery": "156.14",
            "recovery": None,
        },
        # Printed under the label "Claim", not "Total".
        "gross_total": "5068.87",
    },
]

BUILDERS: dict[str, Any] = {
    "DL_Auda_format_1_assessment.docx": build_auda_format_1_assessment,
    "DL_Repair_Invoice_format_1.docx": build_repair_invoice_format_1,
    "DL_Auda_format_2_assessment.docx": build_auda_format_2_assessment,
    "DL_Invoice_2_request_for_payment.docx": build_invoice_2_request_for_payment,
    "DL_Auda_format_3_assessment.docx": build_auda_format_3_assessment,
    "DL_Invoice_3_request_for_payment.docx": build_invoice_3_request_for_payment,
    "DL_Auda_format_4_assessment.docx": build_auda_format_4_assessment,
    "DL_Invoice_4_request_for_payment.docx": build_invoice_4_request_for_payment,
    "DL_Auda_format_7_assessment.docx": build_auda_format_7_assessment,
    "DL_Repair_Invoice_format_7.docx": build_repair_invoice_format_7,
    "DL_Auda_format_5_assessment.docx": build_auda_format_5_assessment,
    "DL_Repair_Invoice_format_5.docx": build_repair_invoice_format_5,
    "DL_Auda_format_6_assessment.docx": build_auda_format_6_assessment,
    "DL_Repair_Invoice_format_6.docx": build_repair_invoice_format_6,
    "EXL_demo_engineer_report.docx": build_exl_demo_engineer_report,
    "EXL_demo_invoice.docx": build_exl_demo_invoice,
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
