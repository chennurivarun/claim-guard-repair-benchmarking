"""Regenerate the Audatex-style ("Auda 7") PDF fixtures with native PyMuPDF text.

Usage (from backend/):

    uv run python scripts/build_auda_fixtures.py

Only ``sample-data/auda-style/Auda7_full_report.pdf`` is regenerated. The page
content ports the previous fixture's three pages (summary, labour work units,
EXTRAS charges — read back via PyMuPDF to preserve their text) and adds the
PARTS schedule page observed on the client's real "Auda N invoice" documents:
part numbers, "Bet." discount percentages, prices, sundry parts and a parts
total. Text is drawn with a monospaced font so column alignment survives
native text extraction.

The other two fixtures in the same directory are deliberately left untouched:
``Auda7_photo_pages.pdf`` contains camera images this generator cannot
reproduce faithfully, and regenerating ``Auda7_format_invoice.pdf`` would
churn a committed byte-identical fixture for no behavioural gain.
"""

from __future__ import annotations

from pathlib import Path

import fitz

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample-data" / "auda-style"
PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN_LEFT = 40
TOP = 60
LEADING = 15
FONT = "cour"
FONT_SIZE = 9

SUMMARY_PAGE = [
    "EXL Repairer Service Ltd",
    "St Clare House, 30-33 Minories, London, EC3N 1DD",
    "Full Report                                  Created: 18/12/2025",
    "Assessment Number: XYZ123456",
    "Summary Information",
    "Claim",
    "Authorisation Status: Authorised     Date of Incident: 03/12/2025",
    "Work Provider: TTH EXL Indirect      Able to Authorise Repairs: TBA",
    "Claim Reference: 2025/ABC/12345      Repairs Authorised?: TBA",
    "Policy Number:                       VAT Status: Non Taxable",
    "Other Reference:                     Repairer: Approved",
    "Vehicle Details",
    "Manufacturer: MERCEDES               Model: SPRINTER 313 CDI WD",
    "Engine: 1.6LTT 66KW                  Registration Number: ABC1234",
    "Registration Year: 2012              Odometer: 24367 miles",
    "Colour: White                        Build date: From J55678",
    "Audatex System Using Manufacturer Times",
]

LABOUR_PAGE = [
    "Assessment Number: XYZ123456         Full Report",
    "Repair Information",
    "LABOUR                               Time Basis 10 WU=1HR.",
    "Repair/Guide",
    "Number         Description                          Work Units",
    "88-3231 01     R + R RIGHT MIRROR                     3",
    "88-3231 01     RENEW R/DOOR MIRROR (REMOVED)          4",
    "               INCLUDES: ASSEMBLE MIRROR",
    "1000           REPAIR UTILITIES ALLOWANCE             15",
    "1000           CHECK AND QUALITY CONTROL              5",
    "1000           CHECK AND PRECHECK                     3",
    "1000           CHECK TECHNICAL INFO                   5",
    "1000           CHECK AND VALET                        13",
    "1000           CHECK FINAL INSPECTION                 5",
    "1000           CHECK VEH DIAG PRE CHECK               10",
    "1000           CHECK VEH DIAG POST CHECK              10",
    "1000           CHECK AND ROAD TEST                    5",
    "1000           ALLOWANCE OLDER VEHICLE                10",
    "1000           CHECK ADAS APPLICATION FEE             5",
    "Total Work Units                                    93",
]

EXTRAS_PAGE = [
    "Assessment Number: XYZ123456         Full Report",
    "EXTRAS",
    "Description                                        Price",
    "E.P.A. Charge                                        GBP 30.00",
    "Car Care Kit                                         GBP 10.00",
    "Pas Uplift                                           GBP 40.00",
    "Estimate Fee                                         GBP 70.00",
    "Pre-Repair Cleaning Charge (Inc Sanitation Methods)  GBP 50.00",
    "Personal Belongings                                  GBP 30.00",
    "Environmental Levement                               GBP 25.00",
    "Energy Cost Supplement and Sustainability            GBP 25.00",
    "Standard Vehicle Shut Down                           GBP 80.00",
    "Yard Charge                                          GBP 70.00",
    "Repair Method Research Charge                        GBP 100.00",
    "Total Extras                                        GBP 536.00",
    "NB- COLOUR CODED ITEMS/TRIM-PART NUMBERS MAY DIFFER",
    "Claim Details: Insurer: EXL INSURER   Insured: John Smith",
    "Audatex System Using Manufacturer Times",
]

PARTS_PAGE = [
    "Assessment Number: XYZ123456         Full Report",
    "PARTS                                Time Basis 10 WU=1HR.",
    "Guide No   Description             Part Number    Bet.   Price",
    "1720       R/SCREW                 0019846529     0%     2.80",
    "1740       R/DOOR MIRROR HSG       0008111122     0%     19.10",
    "1760       R/D-MIRROR INDICATOR    0018229020     0%     27.10",
    "1764       R/OSTRO MIRROR          0008107219     0%     76.00",
    "1768       R/MIRROR FRAME          0008130356     0%     11.75",
    "1768       R/OUT DR MIRROR CVR     0019801133     0%     1.25",
    "1770       R/DOOR MIRROR SEAL      9068110198     0%     0.55",
    "Sub Total                                                139.05",
    "Deduction from RRP                                       0.00",
    "Sundry Parts                                             4.87",
    "Total Parts                                              143.92",
    "Audatex System Using Manufacturer Times",
]

FULL_REPORT_PAGES = [SUMMARY_PAGE, LABOUR_PAGE, EXTRAS_PAGE, PARTS_PAGE]


def build_full_report(path: Path) -> None:
    document = fitz.open()
    for lines in FULL_REPORT_PAGES:
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        y = TOP
        for line in lines:
            page.insert_text(
                (MARGIN_LEFT, y), line, fontname=FONT, fontsize=FONT_SIZE
            )
            y += LEADING
    document.save(path, deflate=True)
    document.close()


def main() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    target = SAMPLE_DIR / "Auda7_full_report.pdf"
    build_full_report(target)
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
