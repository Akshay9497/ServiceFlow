from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from api.finance import line_totals


def _text(value):
    return escape(str(value or "")).replace("\n", "<br/>")


def _money(value):
    return f"INR {value:,.2f}"


def _build_pdf(*, organization, customer, document_type, number, date_label, date_value, secondary_date_label, secondary_date_value, notes, tax_mode, lines, status, totals, extra=None):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{document_type} {number}",
        author="ServiceFlow",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="DocumentTitle",
        parent=styles["Title"],
        alignment=TA_RIGHT,
        textColor=colors.HexColor("#35305f"),
        fontSize=20,
        leading=24,
    ))
    styles.add(ParagraphStyle(
        name="MutedSmall",
        parent=styles["BodyText"],
        textColor=colors.HexColor("#5f6270"),
        fontSize=8,
        leading=11,
    ))
    styles.add(ParagraphStyle(
        name="RightSmall",
        parent=styles["MutedSmall"],
        alignment=TA_RIGHT,
    ))
    story = [
        Table(
            [[
                Paragraph(f"<b>{_text(organization.name)}</b><br/>ServiceFlow business record", styles["BodyText"]),
                Paragraph(document_type.upper(), styles["DocumentTitle"]),
            ]],
            colWidths=[250, 244],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#dcd9ef")),
            ]),
        ),
        Spacer(1, 8 * mm),
    ]
    metadata = [
        [Paragraph("<b>Number</b>", styles["BodyText"]), _text(number),
         Paragraph(f"<b>{_text(date_label)}</b>", styles["BodyText"]), _text(date_value or "Not issued")],
        [Paragraph("<b>Customer</b>", styles["BodyText"]), Paragraph(_text(customer.name), styles["BodyText"]),
         Paragraph("<b>Status</b>", styles["BodyText"]), _text(status)],
        [Paragraph("<b>Contact</b>", styles["BodyText"]), Paragraph(_text(customer.email or customer.phone or "Not provided"), styles["MutedSmall"]),
         Paragraph("<b>GST treatment</b>", styles["BodyText"]), "IGST" if tax_mode == "igst" else "CGST + SGST"],
        [Paragraph(f"<b>{_text(secondary_date_label)}</b>", styles["BodyText"]), _text(secondary_date_value or "—"),
         Paragraph("", styles["BodyText"]), ""],
    ]
    if customer.address:
        metadata.append([
            Paragraph("<b>Address</b>", styles["BodyText"]),
            Paragraph(_text(customer.address), styles["MutedSmall"]),
            Paragraph("", styles["BodyText"]),
            "",
        ])
    story.append(Table(
        metadata,
        colWidths=[56, 200, 63, 175],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]),
    ))
    story.extend([Spacer(1, 8 * mm)])

    line_data = [[
        "Description", "Qty", "Unit price", "GST %", "Taxable", "GST",
    ]]
    for line in lines:
        line_data.append([
            Paragraph(_text(line.description), styles["BodyText"]),
            f"{line.quantity:.3f}",
            _money(line.unit_price),
            f"{line.gst_rate:.2f}",
            _money(line.taxable_amount),
            _money(line.tax_amount),
        ])
    story.append(Table(
        line_data,
        colWidths=[190, 43, 67, 42, 77, 75],
        repeatRows=1,
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0eff9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#35305f")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dedee7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]),
    ))
    summary = [
        ["Taxable subtotal", _money(totals["subtotal"])],
        ["GST total", _money(totals["tax"])],
        ["Total", _money(totals["total"])],
    ]
    if extra:
        summary.extend(extra)
    story.extend([
        Spacer(1, 5 * mm),
        Table(
            summary,
            colWidths=[140, 105],
            hAlign="RIGHT",
            style=TableStyle([
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#77718e")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]),
        ),
    ])
    if notes:
        story.extend([
            Spacer(1, 7 * mm),
            Paragraph("<b>Notes</b>", styles["BodyText"]),
            Paragraph(_text(notes), styles["MutedSmall"]),
        ])
    story.extend([
        Spacer(1, 10 * mm),
        Paragraph(
            "<b>Important:</b> This management document is generated from "
            "ServiceFlow records and is not a statutory GST tax invoice. Verify "
            "tax treatment and statutory invoice details before issuing or filing.",
            styles["MutedSmall"],
        ),
    ])
    document.build(story)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{number}.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


def invoice_pdf(invoice):
    allocations = invoice.allocations.filter(
        reversed_at__isnull=True,
        payment__status="received",
    )
    allocated_total = sum(
        (allocation.amount for allocation in allocations),
        start=Decimal("0.00"),
    )
    totals = line_totals(invoice.lines)
    totals["allocated"] = allocated_total
    totals["outstanding"] = (
        max(totals["total"] - allocated_total, 0)
        if invoice.status == "issued"
        else 0
    )
    return _build_pdf(
        organization=invoice.organization,
        customer=invoice.customer,
        document_type="Invoice summary",
        number=invoice.invoice_number,
        date_label="Issue date",
        date_value=invoice.issue_date,
        secondary_date_label="Due date",
        secondary_date_value=invoice.due_date,
        notes=invoice.notes,
        tax_mode=invoice.tax_mode,
        lines=invoice.lines.all(),
        status=invoice.status,
        totals=totals,
        extra=[
            ["Received", _money(totals["allocated"])],
            ["Outstanding", _money(totals["outstanding"])],
        ],
    )


def quotation_pdf(quotation):
    return _build_pdf(
        organization=quotation.organization,
        customer=quotation.customer,
        document_type="Quotation",
        number=quotation.quotation_number,
        date_label="Prepared",
        date_value=quotation.created_at.date(),
        secondary_date_label="Valid until",
        secondary_date_value=quotation.valid_until,
        notes=quotation.notes,
        tax_mode=quotation.tax_mode,
        lines=quotation.lines.all(),
        status=quotation.status,
        totals=line_totals(quotation.lines),
    )
