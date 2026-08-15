"""Generate five governed Engineer Assessment + Repair Invoice claim pairs."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample-data" / "engineer-invoice-pairs"
VAT = Decimal("0.20")
BASE = (
    ("labour", "865246R77", "Front bumper remove and refit", Decimal("1"), Decimal("78.50")),
    ("labour", "865246R77AX", "Radiator grille remove and refit", Decimal("0.3"), Decimal("78.50")),
    ("labour", "991088A00", "Radar sensor calibrate", Decimal("0.3"), Decimal("78.50")),
    ("paint", "0281", "Front bumper repair paint plastic", Decimal("1"), Decimal("94.20")),
    ("extra", "RECOVERY", "Standard vehicle recovery", Decimal("1"), Decimal("150.00")),
)
SCENARIOS = (
    ("close agreement", (Decimal("1.00"),) * 5),
    ("small differences", (Decimal("1.04"), Decimal("1.05"), Decimal("1.00"), Decimal("1.03"), Decimal("1.00"))),
    ("labour variance", (Decimal("1.22"), Decimal("1.20"), Decimal("1.18"), Decimal("1.00"), Decimal("1.00"))),
    ("parts and paint variance", (Decimal("1.00"), Decimal("1.00"), Decimal("1.00"), Decimal("1.32"), Decimal("1.15"))),
    ("multiple meaningful differences", (Decimal("1.30"), Decimal("1.25"), Decimal("1.20"), Decimal("1.38"), Decimal("1.28"))),
)


def money(value: Decimal) -> str:
    value = Decimal(str(value))
    return f"£{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def header_table(rows):
    return Table(rows, colWidths=[38 * mm, 52 * mm, 38 * mm, 52 * mm], style=TableStyle([
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#CBD5E1")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))


def build_engineer(sequence: int, fixture: dict) -> Path:
    path = OUT / f"CLM-UK-{sequence:03d}_Engineer_Assessment.pdf"
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14*mm, rightMargin=14*mm,
                            topMargin=12*mm, bottomMargin=12*mm,
                            title=f"Engineer Assessment {fixture['assessment_number']}")
    machine_evidence_style = ParagraphStyle(
        "MachineEvidence",
        parent=styles["BodyText"],
        fontSize=1,
        leading=1,
        textColor=colors.white,
        spaceBefore=0,
        spaceAfter=0,
    )
    story = [
        Paragraph("ENGINEER ASSESSMENT REPORT", styles["Title"]),
        Paragraph("Representative Audatex-style assessment using manufacturer times", styles["Heading3"]),
        Spacer(1, 4*mm),
        header_table([
            ["Assessment Number", fixture["assessment_number"], "Created", fixture["created"]],
            ["Claim Reference", fixture["claim_reference"], "Date of Incident", fixture["incident_date"]],
            ["Policy Number", fixture["policy_number"], "Authorisation Status", "Authorised"],
            ["Registration", fixture["registration"], "VIN", fixture["vin"]],
            ["Manufacturer", "HYUNDAI", "Model", "KONA HYBRID"],
            ["Variant", "ADVANCE 129 AUTO", "Odometer", f"{fixture['mileage']:,}"],
        ]),
        Spacer(1, 5*mm),
        Paragraph("VEHICLE CONDITION", styles["Heading2"]),
        Paragraph("Pre-Accident Condition: Good", styles["BodyText"]),
        Paragraph("Severity of Impact: Light", styles["BodyText"]),
        Paragraph("Vehicle Status on Inspection: Unroadworthy", styles["BodyText"]),
        Paragraph("Damage Areas: Front bumper, radiator grille, front radar sensor", styles["BodyText"]),
        Spacer(1, 5*mm),
        Paragraph("REPAIR INFORMATION", styles["Heading2"]),
    ]
    op_rows = [["Category", "Code", "Description", "Qty/Hrs", "Rate", "Total"]]
    for category, code, desc, quantity, unit_price in BASE:
        total = q(quantity * unit_price)
        op_rows.append([category.title(), code, desc, str(quantity), money(unit_price), money(total)])
        # Visible machine-readable evidence row; retained in extracted text and audit payload.
        work_units = q(quantity * Decimal("10")) if category in {"labour", "paint"} else Decimal("0")
        hours = quantity if category in {"labour", "paint"} else Decimal("0")
        story.append(Paragraph(
            f"OP|{category}|{code}|{desc}|{work_units}|{hours}|{quantity}|{unit_price}|{total}",
            machine_evidence_style,
        ))
    story.append(Table(op_rows, colWidths=[19*mm, 25*mm, 75*mm, 18*mm, 22*mm, 24*mm], repeatRows=1,
        style=TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17324D")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#CBD5E1")),
            ("FONTSIZE", (0,0), (-1,-1), 7.6), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ])))
    labour = sum(q(qty*rate) for cat,_,_,qty,rate in BASE if cat == "labour")
    paint = sum(q(qty*rate) for cat,_,_,qty,rate in BASE if cat == "paint")
    parts = sum(q(qty*rate) for cat,_,_,qty,rate in BASE if cat == "part")
    extras = sum(q(qty*rate) for cat,_,_,qty,rate in BASE if cat == "extra")
    subtotal = labour + paint + parts + extras
    vat = q(subtotal * VAT)
    gross = subtotal + vat
    story.extend([Spacer(1, 6*mm), Paragraph("CALCULATION", styles["Heading2"]),
        Paragraph("Labour Rate: £78.50", styles["BodyText"]),
        Paragraph("Paint Rate: £78.50", styles["BodyText"]),
        Paragraph(f"Total Labour: {money(labour)}", styles["BodyText"]),
        Paragraph(f"Total Paint/Material Costs: {money(paint)}", styles["BodyText"]),
        Paragraph(f"Total Parts: {money(parts)}", styles["BodyText"]),
        Paragraph(f"Total Additional Costs: {money(extras)}", styles["BodyText"]),
        Paragraph(f"Grand Total Excl VAT: {money(subtotal)}", styles["BodyText"]),
        Paragraph("VAT Rate: 20%", styles["BodyText"]), Paragraph(f"VAT: {money(vat)}", styles["BodyText"]),
        Paragraph(f"Grand Total Incl VAT: {money(gross)}", styles["Heading3"]),
        PageBreak(), Paragraph("ENGINEER ASSESSMENT REPORT — SOURCE EVIDENCE", styles["Title"]),
        Paragraph("Assessment Number: " + fixture["assessment_number"], styles["Heading3"]),
        Paragraph(
            "This page preserves the inspection context used alongside the priced operations. "
            "No price is inferred from an image or diagram.",
            styles["BodyText"],
        ),
        Spacer(1, 6*mm),
        Table(
            [
                ["INSPECTION CONTEXT", "DAMAGE SUMMARY"],
                [
                    "Vehicle photographed during engineer inspection\n"
                    "Pre-accident condition: Good\n"
                    "Inspection status: Unroadworthy",
                    "Front bumper\nRadiator grille\nFront radar sensor",
                ],
            ],
            colWidths=[88*mm, 88*mm],
            rowHeights=[10*mm, 50*mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F8FAFC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]),
        ),
        Spacer(1, 8*mm),
        Paragraph("AUDIT NOTE", styles["Heading2"]),
        Paragraph(
            "The structured operation rows on the preceding page remain the governed source for "
            "engineer quantities, rates and totals. This supporting page is retained for traceability only.",
            styles["BodyText"],
        ),
    ])
    doc.build(story)
    return path


def build_invoice(sequence: int, fixture: dict, multipliers: tuple[Decimal, ...]) -> Path:
    path = OUT / f"CLM-UK-{sequence:03d}_Repair_Invoice.pdf"
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14*mm, rightMargin=14*mm,
                            topMargin=12*mm, bottomMargin=12*mm,
                            title=f"Repair Invoice INV-{fixture['claim_reference']}")
    rows = []
    parts = labour = Decimal("0")
    for (category, _code, description, quantity, base_price), multiplier in zip(BASE, multipliers):
        unit = q(base_price * multiplier)
        total = q(quantity * unit)
        (locals())
        if category in {"labour", "paint"}:
            labour += total
        else:
            parts += total
        rows.append([description, str(quantity), money(unit), money(total)])
    subtotal = q(parts + labour); vat = q(subtotal * VAT); gross = subtotal + vat
    story = [Paragraph("REPAIR INVOICE", styles["Title"]),
        header_table([
            ["Invoice number", f"INV-{fixture['claim_reference']}", "Invoice date", fixture["created"]],
            ["Registration", fixture["registration"], "Vehicle", "HYUNDAI KONA HYBRID"],
            ["Repairer", fixture["repairer"], "Mileage", f"{fixture['mileage']:,}"],
        ]), Spacer(1, 5*mm),
        Table([["Description", "Qty", "Unit price", "Net subtotal"], *rows],
            colWidths=[104*mm, 20*mm, 27*mm, 31*mm], repeatRows=1,
            style=TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17324D")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#CBD5E1")),
                ("ALIGN", (1,1), (-1,-1), "RIGHT"), ("FONTSIZE", (0,0), (-1,-1), 8.2),
            ])), Spacer(1, 6*mm),
        Paragraph(f"Parts net {money(parts)}", styles["BodyText"]),
        Paragraph(f"Labour net {money(labour)}", styles["BodyText"]),
        Paragraph(f"Subtotal net {money(subtotal)}", styles["BodyText"]),
        Paragraph(f"VAT (20%) {money(vat)}", styles["BodyText"]),
        Paragraph(f"Invoice Total {money(gross)}", styles["Heading2"]),
    ]
    doc.build(story)
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, (scenario, multipliers) in enumerate(SCENARIOS, start=1):
        claim_reference = f"CLM-UK-{index:03d}"
        fixture = {
            "claim_reference": claim_reference,
            "assessment_number": f"EA-{index:04d}",
            "policy_number": f"POL-UK-{2026000 + index}",
            "registration": f"CG{index:02d} UKX",
            "vin": f"TMAJ3813DMJ{10000 + index:05d}",
            "created": (date(2026, 8, 1) + timedelta(days=index)).strftime("%d/%m/%Y"),
            "incident_date": (date(2026, 7, 20) + timedelta(days=index)).strftime("%d/%m/%Y"),
            "mileage": 12000 + index * 875,
            "repairer": f"UK Demonstration Repair Centre {index}",
            "scenario": scenario,
        }
        engineer = build_engineer(index, fixture)
        invoice = build_invoice(index, fixture, multipliers)
        manifest.append({**fixture, "engineer_report": engineer.name, "repair_invoice": invoice.name})
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated {len(manifest)} claim pairs / {len(manifest)*2} PDFs in {OUT}")


if __name__ == "__main__":
    main()
