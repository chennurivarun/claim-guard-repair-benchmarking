"""Native PDFs, with visible synthetic labels; no database insertion or hidden text.

Repair descriptions follow sample-data/client-formats format 1. All identities
and prices are invented. Use a fresh demonstration claim, never production data.
"""

import json
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pdf/benchmark-comparison-demo"
ITEMS = [
    ("1781", "L/R DOOR", Decimal("1")),
    ("2185", "L/SILL PANEL COVER", Decimal(".4")),
    ("1000", "Door Fitting Kit", Decimal(".1")),
]
SOURCES = [
    ("01-third-party", "historical_claim", "TP", [100, 110, 120]),
    ("02-in-house", "in_house", "IH", [80, 90, 100]),
    ("03-new-invoices", "live", "NEW", [150, 160, 170]),
]


def table(rows, widths):
    return Table(
        rows,
        colWidths=widths,
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        ),
    )


def generate():
    styles = getSampleStyleSheet()
    manifest = []
    for source_index, (folder, group, prefix, prices) in enumerate(SOURCES, 1):
        for i, base in enumerate(prices, 1):
            ref = f"DEMO-{prefix}-{i:03}"
            reg = f"DM{source_index}{i}XYZ"
            assessment = f"EA-{prefix}-{i:03}"
            amounts = [Decimal(base) * factor for _, _, factor in ITEMS]
            net = sum(amounts)
            vat = net * Decimal(".2")
            for kind in ("invoice", "assessment"):
                directory = (
                    OUT / folder / ("invoices" if kind == "invoice" else "assessments")
                )
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / f"{ref}-{kind}.pdf"
                story = [
                    Paragraph("SYNTHETIC DEMO - NOT A REAL CLAIM", styles["Heading2"]),
                    Paragraph(
                        "REPAIR INVOICE"
                        if kind == "invoice"
                        else "ENGINEER ASSESSMENT REPORT",
                        styles["Title"],
                    ),
                    Paragraph(
                        "Demo Motor Repairs Ltd - test documents only",
                        styles["BodyText"],
                    ),
                    Spacer(1, 12),
                ]
                for label, value in [
                    (
                        "Invoice Number" if kind == "invoice" else "Assessment Number",
                        ref if kind == "invoice" else assessment,
                    ),
                    ("Date", "26/09/2026"),
                    ("Claim Reference", ref),
                    ("Policy Number", f"POL-{prefix}-{i:03}"),
                    ("Registration", reg),
                    ("Manufacturer", "HYUNDAI"),
                    ("Model", "i30"),
                    ("Vehicle", "HYUNDAI i30"),
                ]:
                    story.append(Paragraph(f"{label}: {value}", styles["BodyText"]))
                story.extend([Spacer(1, 20), Paragraph("PARTS", styles["Heading2"])])
                if kind == "invoice":
                    rows = [["Description", "Qty", "Unit price", "Net subtotal"]]
                    rows += [
                        [desc, "1", f"{amount:.2f}", f"{amount:.2f}"]
                        for (_, desc, _), amount in zip(ITEMS, amounts, strict=True)
                    ]
                    story.append(table(rows, [265, 40, 90, 100]))
                else:
                    rows = [["Guide", "Description", "Price"]] + [
                        [code, desc, f"{amount:.2f}"]
                        for (code, desc, _), amount in zip(ITEMS, amounts, strict=True)
                    ]
                    story.append(table(rows, [65, 330, 100]))
                story.append(Spacer(1, 20))
                for label, value in [
                    ("Total Parts", net),
                    ("Net Total", net),
                    ("VAT at 20%", vat),
                    ("Grand Total Incl VAT", net + vat),
                ]:
                    story.append(
                        Paragraph(f"{label}: £{value:.2f}", styles["BodyText"])
                    )
                story.extend(
                    [
                        Spacer(1, 24),
                        Paragraph(
                            "All prices are invented for comparison testing. Currency: GBP. Quantities: one per item.",
                            styles["BodyText"],
                        ),
                    ]
                )
                SimpleDocTemplate(
                    str(path),
                    pagesize=A4,
                    leftMargin=50,
                    rightMargin=50,
                    topMargin=40,
                    bottomMargin=40,
                ).build(story)
                manifest.append(
                    {
                        "file": str(path.relative_to(OUT)),
                        "source": group,
                        "kind": kind,
                        "reference": ref,
                        "registration": reg,
                        "amounts": [f"{a:.2f}" for a in amounts],
                        "rolled_up": False,
                    }
                )
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    print(f"Created {len(generate())} demo PDFs in {OUT}")
