"""Generate the ten-invoice P90 and ontology-normalisation demonstration set."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from shutil import copy2

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output" / "pdf" / "p90-demo-invoice-set"
STORAGE_DIR = PROJECT_ROOT / "backend" / "data" / "storage" / "cases"
MOT_AMOUNT = Decimal("54.85")
PRICE_MULTIPLIERS = (
    Decimal("0.95"),
    Decimal("1.00"),
    Decimal("1.05"),
    Decimal("1.10"),
    Decimal("1.20"),
    Decimal("1.40"),
    Decimal("1.80"),
    Decimal("2.50"),
)
REPAIRERS = (
    "Northfield Motor Repairs",
    "Riverside Auto Centre",
    "Metro Vehicle Services",
    "Northfield Motor Repairs",
    "Riverside Auto Centre",
    "Metro Vehicle Services",
    "Northfield Motor Repairs",
    "Citywide Repair Group",
)

DESCRIPTION_ALIASES = {
    "Oil & Filter Disposal": (
        "Oil Disposal",
        "Oil and Filter Disposal",
        "Waste Oil Disposal",
        "Environmental Oil Disposal",
        "Oil/Filter Disposal Charge",
        "Oil Disposal Fee",
        "Waste Oil and Filter",
        "Oil & Filter Disposal",
    ),
    "Oil Filter": (
        "Oil Filter",
        "OL Filter",
        "Oil_Fil",
        "Engine Oil Filter",
        "Oil Filter Element",
        "Filter - Oil",
        "OIL-FLTR",
        "Oilfilter",
    ),
    "Air Filter": (
        "Air Filter",
        "Engine Air Filter",
        "Air_Filter",
        "Air Filter Element",
        "Air Filter",
        "Engine Air Filter",
        "Air_Filter",
        "Air Filter Element",
    ),
    "Pollen Filter": (
        "Pollen Filter",
        "Cabin Pollen Filter",
        "Pollen_Filter",
        "Cabin Filter",
        "Pollen Filter",
        "Cabin Pollen Filter",
        "Pollen_Filter",
        "Cabin Filter",
    ),
}

# The descriptions and quantities deliberately match the existing pilot invoice pattern.
BASE_LINES = (
    ("Oil & Filter Disposal", Decimal("1"), Decimal("4.50"), "part"),
    ("Oil Filter", Decimal("1"), Decimal("10.60"), "part"),
    ("Air Filter", Decimal("1"), Decimal("25.31"), "part"),
    ("Pollen Filter", Decimal("1"), Decimal("14.28"), "part"),
    ("Spark Plugs", Decimal("4"), Decimal("9.95"), "part"),
    ("Sundries - Grease/Oil Etc", Decimal("1"), Decimal("4.50"), "part"),
    ("Oil System Flush And Cleaner", Decimal("1"), Decimal("8.50"), "part"),
    ("Screen Wash", Decimal("1"), Decimal("1.50"), "part"),
    ("Fuel Injection Treatment", Decimal("1"), Decimal("10.00"), "part"),
    ("Sump Sealing Washer", Decimal("1"), Decimal("1.50"), "part"),
    ("Brake Cleaner", Decimal("1"), Decimal("1.50"), "part"),
    ("Fully Synthetic Engine Oil 5W30", Decimal("4"), Decimal("12.00"), "part"),
    ("Track Rod Ends", Decimal("2"), Decimal("25.02"), "part"),
    ("Carried Out Full Service", Decimal("2"), Decimal("95.00"), "labour"),
    ("Fit Track Rod Ends", Decimal("0.8"), Decimal("95.00"), "labour"),
)


def money(value: Decimal) -> str:
    return f"£{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def scaled(value: Decimal, multiplier: Decimal) -> Decimal:
    return (value * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_invoice(sequence: int, multiplier: Decimal) -> Path:
    variant_index = sequence - 3
    repairer = REPAIRERS[variant_index]
    invoice_number = 9500 + sequence
    invoice_date = date(2026, 1, 15) + timedelta(days=variant_index * 7)
    registration = f"CG{sequence:02d} DEM"
    output_path = OUTPUT_DIR / f"Invoice_{sequence:02d}_Variant.pdf"
    styles = getSampleStyleSheet()
    right = ParagraphStyle("right", parent=styles["Normal"], alignment=TA_RIGHT)
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Repair invoice {invoice_number}",
        author=repairer,
    )

    rows = []
    parts_total = Decimal("0")
    labour_total = Decimal("0")
    for description, quantity, base_unit, line_type in BASE_LINES:
        description = DESCRIPTION_ALIASES.get(description, (description,) * 8)[variant_index]
        unit_price = scaled(base_unit, multiplier)
        subtotal = scaled(quantity * unit_price, Decimal("1"))
        if line_type == "labour":
            labour_total += subtotal
        else:
            parts_total += subtotal
        rows.append(
            [description, str(quantity.normalize()), money(unit_price), money(subtotal)]
        )

    taxable_total = parts_total + labour_total
    vat = scaled(taxable_total, Decimal("0.20"))
    gross_total = taxable_total + vat + MOT_AMOUNT

    story = [
        Paragraph(repairer.upper(), styles["Title"]),
        Paragraph("Service and repair statement", styles["Heading3"]),
        Paragraph(
            f"Invoice #{invoice_number} Date: {invoice_date.strftime('%d/%m/%Y')}",
            styles["Heading4"],
        ),
        Spacer(1, 3 * mm),
        Table(
            [
                ["Invoice number", str(invoice_number), "Invoice date", invoice_date.strftime("%d/%m/%Y")],
                ["Registration", registration, "Vehicle", "Vauxhall Adam Glam"],
                ["Repairer", repairer, "Mileage", f"{100_000 + sequence * 425:,}"],
            ],
            colWidths=[31 * mm, 48 * mm, 31 * mm, 68 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F4F6")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        ),
        Spacer(1, 5 * mm),
    ]

    line_table = Table(
        [["Description", "Qty", "Unit price", "Net subtotal"], *rows],
        colWidths=[101 * mm, 18 * mm, 28 * mm, 31 * mm],
        repeatRows=1,
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.3),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ]
        ),
    )
    story.extend([line_table, Spacer(1, 5 * mm)])

    summary = Table(
        [
            ["Parts net", money(parts_total)],
            ["Labour net", money(labour_total)],
            ["VAT (20%)", money(vat)],
            ["MOT (non-VAT)", money(MOT_AMOUNT)],
            ["TOTAL", money(gross_total)],
        ],
        colWidths=[48 * mm, 36 * mm],
        hAlign="RIGHT",
        style=TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, -2), "Helvetica"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#DBEAFE")),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#17324D")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        ),
    )
    story.extend(
        [
            summary,
            Spacer(1, 4 * mm),
            Paragraph(
                "Payment due within 14 days. All repair charges are shown before VAT.",
                right,
            ),
        ]
    )
    document.build(story)
    return output_path


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for original_number in (1, 2):
        source = next(STORAGE_DIR.rglob(f"Original_Invoice_{original_number}.pdf"))
        copy2(source, OUTPUT_DIR / f"Invoice_{original_number:02d}_Original.pdf")
    for sequence, multiplier in enumerate(PRICE_MULTIPLIERS, start=3):
        build_invoice(sequence, multiplier)


if __name__ == "__main__":
    main()
