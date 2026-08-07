"""PDF negotiation letter with LibreOffice fidelity and ReportLab fallback."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.exports.common import money_label, percentage_label
from app.exports.docx_export import build_negotiation_docx
from app.exports.letter_context import (
    LetterFacts,
    build_letter_facts,
    deterministic_line_sentence,
)

NAVY = colors.HexColor("#17324D")
BLUE = colors.HexColor("#2E74B5")
DARK_BLUE = colors.HexColor("#1F4D78")
GOLD = colors.HexColor("#7A5A00")
GRAY = colors.HexColor("#5B656F")
PALE_BLUE = colors.HexColor("#E8EEF5")
PALE_GRAY = colors.HexColor("#F4F6F9")
GRID = colors.HexColor("#D8DEE6")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "ClaimGuardBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=12.5,
            textColor=colors.HexColor("#1F2933"),
            spaceAfter=6,
        ),
        "kicker": ParagraphStyle(
            "ClaimGuardKicker",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=10,
            textColor=GOLD,
            spaceAfter=2,
        ),
        "title": ParagraphStyle(
            "ClaimGuardTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            alignment=TA_LEFT,
            textColor=NAVY,
            spaceBefore=0,
            spaceAfter=7,
        ),
        "subtitle": ParagraphStyle(
            "ClaimGuardSubtitle",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=12,
            leading=15,
            textColor=GRAY,
            spaceAfter=14,
        ),
        "h1": ParagraphStyle(
            "ClaimGuardH1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            textColor=BLUE,
            spaceBefore=12,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "ClaimGuardH3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=DARK_BLUE,
            spaceBefore=4,
            spaceAfter=2,
            keepWithNext=True,
        ),
        "small": ParagraphStyle(
            "ClaimGuardSmall",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.3,
            leading=10,
            textColor=colors.HexColor("#1F2933"),
        ),
        "small_right": ParagraphStyle(
            "ClaimGuardSmallRight",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.3,
            leading=10,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#1F2933"),
        ),
        "note": ParagraphStyle(
            "ClaimGuardNote",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=10.5,
            textColor=GRAY,
            spaceBefore=3,
            spaceAfter=6,
        ),
    }


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text or "")), style)


def _header_footer(canvas: Any, document: Any, facts: LetterFacts) -> None:
    canvas.saveState()
    canvas.setStrokeColor(GRID)
    canvas.setLineWidth(0.5)
    canvas.line(inch, LETTER[1] - 0.62 * inch, LETTER[0] - inch, LETTER[1] - 0.62 * inch)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(NAVY)
    canvas.drawString(inch, LETTER[1] - 0.5 * inch, "ClaimGuard")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GRAY)
    canvas.drawRightString(LETTER[0] - inch, LETTER[1] - 0.5 * inch, f"Case {facts.case_reference}")
    canvas.drawRightString(
        LETTER[0] - inch,
        0.5 * inch,
        f"ClaimGuard | {facts.report_date} | Page {document.page}",
    )
    canvas.restoreState()


def _metadata_table(facts: LetterFacts, styles: dict[str, ParagraphStyle]) -> Table:
    rows = [
        ("Case", facts.case_reference),
        ("Claim", facts.claim_number),
        ("Invoice", facts.invoice_references),
        ("Vehicle", facts.vehicle_registration),
        ("Prepared for", facts.recipient),
        ("Prepared by", facts.paying_insurer),
        ("Liability", f"{facts.liability_status} - human confirmed"),
        ("Date", facts.report_date),
    ]
    table = Table(
        [[_p(label, styles["small"]), _p(value, styles["small"])] for label, value in rows],
        colWidths=(1.181 * inch, 5.319 * inch),
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), PALE_GRAY),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (0, -1), NAVY),
                ("GRID", (0, 0), (-1, -1), 0.4, GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _summary_table(facts: LetterFacts, styles: dict[str, ParagraphStyle]) -> Table:
    summary = facts.summary
    rows = [
        ("Invoice Price", f"{money_label(summary.invoice_price_net)} net"),
        ("Challenge Price", f"{money_label(summary.challenge_price_net)} net - proposed payable"),
        ("Challenge Amount", f"{money_label(summary.challenge_amount_net)} net"),
        ("VAT impact", money_label(summary.vat_impact)),
        ("Gross effect", money_label(summary.gross_effect)),
        ("MOT / non-VAT", f"{money_label(summary.mot_non_vat_total)} outside VAT"),
        ("Reduction", percentage_label(summary.challenge_percentage)),
    ]
    table = Table(
        [[_p(label, styles["small"]), _p(value, styles["small"])] for label, value in rows],
        colWidths=(1.181 * inch, 5.319 * inch),
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), PALE_GRAY),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (0, -1), NAVY),
                ("GRID", (0, 0), (-1, -1), 0.4, GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _challenge_table(facts: LetterFacts, styles: dict[str, ParagraphStyle]) -> Table:
    header = [
        _p("Item", styles["small"]),
        _p("Invoice net", styles["small"]),
        _p("Challenge Price", styles["small"]),
        _p("Challenge Amount", styles["small"]),
        _p("Basis", styles["small"]),
    ]
    rows = [header]
    for line in facts.lines:
        rows.append(
            [
                _p(line.description, styles["small"]),
                _p(money_label(line.invoice_net), styles["small_right"]),
                _p(money_label(line.challenge_price_net), styles["small_right"]),
                _p(money_label(line.challenge_amount_net), styles["small_right"]),
                _p(line.benchmark_source, styles["small"]),
            ]
        )
    table = Table(
        rows,
        colWidths=(2.2 * inch, 0.8 * inch, 1.0 * inch, 1.0 * inch, 1.5 * inch),
        hAlign="LEFT",
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PALE_BLUE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
                ("GRID", (0, 0), (-1, -1), 0.4, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _reportlab_pdf(facts: LetterFacts, output_path: Path) -> None:
    styles = _styles()
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=0.82 * inch,
        bottomMargin=0.72 * inch,
        title=f"ClaimGuard negotiation letter - {facts.case_reference}",
        author="ClaimGuard",
        subject="Motor invoice Challenge Price and supporting evidence",
    )
    story: list[Any] = [
        _p("CLAIM NEGOTIATION BRIEF", styles["kicker"]),
        _p(
            f"Challenge Price: {money_label(facts.summary.challenge_price_net)} net",
            styles["title"],
        ),
        _p(
            "The proposed payable amount after deterministic review of the approved invoice lines.",
            styles["subtitle"],
        ),
        _metadata_table(facts, styles),
        _p("Position and proposal", styles["h1"]),
        _p("Dear Claims Team,", styles["body"]),
        _p(
            f"We have reviewed invoice {facts.invoice_references} for vehicle "
            f"{facts.vehicle_registration}. The recorded liability position is "
            f"{facts.liability_status}; it was confirmed by {facts.liability_confirmed_by}"
            f"{f' on {facts.liability_confirmed_at}' if facts.liability_confirmed_at else ''}. "
            "This letter reports that human-confirmed position and does not infer liability from the invoice.",
            styles["body"],
        ),
        _p(
            f"The Invoice Price is {money_label(facts.summary.invoice_price_net)} net. "
            f"Our Challenge Price is {money_label(facts.summary.challenge_price_net)} net "
            f"(the proposed payable amount), producing a Challenge Amount of "
            f"{money_label(facts.summary.challenge_amount_net)} net.",
            styles["body"],
        ),
        _p("Financial summary", styles["h1"]),
        _summary_table(facts, styles),
        _p(
            "All line evidence and the Challenge Price are stated net. VAT impact is shown separately; "
            "MOT and other non-VAT charges remain outside the VAT computation.",
            styles["note"],
        ),
        _p("Approved challenged lines", styles["h1"]),
        _challenge_table(facts, styles),
        _p("Evidence by line", styles["h1"]),
    ]
    for index, line in enumerate(facts.lines, start=1):
        story.append(
            KeepTogether(
                [
                    _p(f"{index}. {line.description}", styles["h3"]),
                    _p(deterministic_line_sentence(line), styles["body"]),
                ]
            )
        )
    story.extend(
        [
            _p("Response requested", styles["h1"]),
            _p(
                "Please confirm acceptance of the Challenge Price or provide line-specific evidence "
                "supporting the disputed charges. The calculation can be reconciled directly to the "
                "approved rows above.",
                styles["body"],
            ),
            Spacer(1, 6),
            _p("Yours faithfully,", styles["body"]),
            Paragraph(
                f"<b>{escape(facts.paying_insurer)}</b><br/>Claims team",
                styles["body"],
            ),
        ]
    )
    document.build(
        story,
        onFirstPage=lambda canvas, doc: _header_footer(canvas, doc, facts),
        onLaterPages=lambda canvas, doc: _header_footer(canvas, doc, facts),
    )


def _libreoffice_pdf(result: Mapping[str, Any], destination: Path) -> bool:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        return False
    with TemporaryDirectory(prefix="claimguard-pdf-") as directory:
        temp = Path(directory)
        docx_path = temp / "negotiation-letter.docx"
        build_negotiation_docx(result, docx_path)
        profile = temp / "lo-profile"
        profile.mkdir()
        environment = os.environ.copy()
        environment["HOME"] = str(profile)
        environment.setdefault("TMPDIR", "/private/tmp")
        command = [
            executable,
            "--headless",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(temp),
            str(docx_path),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        generated = temp / "negotiation-letter.pdf"
        if not generated.exists() or generated.stat().st_size == 0:
            return False
        shutil.copyfile(generated, destination)
        return True


def build_negotiation_pdf(
    result: Mapping[str, Any],
    output_path: str | Path,
    *,
    method: str = "auto",
) -> Path:
    """Build a PDF using DOCX/LibreOffice when available, else ReportLab.

    ``method`` may be ``auto``, ``libreoffice`` or ``reportlab``.  ``auto``
    falls back safely; explicit ``libreoffice`` raises when conversion fails.
    """

    if method not in {"auto", "libreoffice", "reportlab"}:
        raise ValueError("method must be 'auto', 'libreoffice' or 'reportlab'")
    facts = build_letter_facts(result)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        prefix=f".{path.stem}-", suffix=".pdf", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        converted = False
        if method in {"auto", "libreoffice"}:
            converted = _libreoffice_pdf(result, temporary)
            if method == "libreoffice" and not converted:
                raise RuntimeError("LibreOffice PDF conversion failed")
        if not converted:
            _reportlab_pdf(facts, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
