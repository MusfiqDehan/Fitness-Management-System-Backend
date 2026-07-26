"""Expense voucher PDF generation (on-demand render; voucher_no assigned at create)."""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from apps.billing.models import Expense


def ensure_expense_voucher_no(expense: Expense) -> Expense:
    """Assign EXP-###### when missing (create path and PDF fallback for legacy rows)."""
    if (expense.voucher_no or "").strip():
        return expense
    expense.voucher_no = f"EXP-{expense.id:06d}"
    expense.save(update_fields=["voucher_no"])
    return expense


def render_expense_voucher_pdf(
    expense: Expense,
    tenant_name: str,
    generated_by: str,
) -> bytes:
    """Branded PDF expense voucher — same visual language as payment invoices."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    from apps.billing.views import (
        _get_invoice_fonts,
        _pdf_clean_text,
        _pdf_draw_lines,
        _pdf_shorten_text,
        _pdf_wrap_text,
    )

    expense = ensure_expense_voucher_no(expense)
    width, height = A4
    left = 20 * mm
    right = width - (20 * mm)
    top = height - (20 * mm)

    voucher_no = expense.voucher_no
    amount = f"TK. {Decimal(expense.amount):,.2f}"
    expense_date = expense.expense_date.strftime("%d %b %Y")
    title = _pdf_clean_text(expense.title)
    receiver = _pdf_clean_text(expense.receiver or "—")
    category_name = _pdf_clean_text(
        expense.category.name if expense.category_id else "—"
    )
    branch_name = _pdf_clean_text(
        expense.branch.name if expense.branch_id else "Company-wide"
    )
    description = _pdf_clean_text(expense.description or "No additional notes.")
    generated_by_name = _pdf_clean_text(generated_by or "System")
    tenant_label = _pdf_clean_text(tenant_name or "Fithive")
    attachment_count = expense.attachments.count() if hasattr(expense, "attachments") else 0

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    regular_font, bold_font = _get_invoice_fonts()

    brand_black = colors.HexColor("#101010")
    brand_yellow = colors.HexColor("#FFC733")
    brand_surface = colors.white
    brand_surface_warm = colors.HexColor("#FFF9EE")
    border_color = colors.HexColor("#E8D39A")
    text_main = colors.HexColor("#171717")
    text_muted = colors.HexColor("#6B6558")

    def draw_field(x, top_y, label, value, field_width, value_font=None, value_size=10, max_lines=1):
        current_value_font = value_font or bold_font
        pdf.setFillColor(text_muted)
        pdf.setFont(regular_font, 8.4)
        pdf.drawString(x, top_y, label.upper())
        lines = _pdf_wrap_text(
            pdf, value, field_width, current_value_font, value_size, max_lines=max_lines
        )
        _pdf_draw_lines(
            pdf,
            x,
            top_y - (4.8 * mm),
            lines,
            current_value_font,
            value_size,
            text_main,
            4.2 * mm,
        )

    pdf.setFillColor(brand_surface)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)

    pdf.setFillColor(brand_black)
    pdf.rect(0, height - (48 * mm), width, 48 * mm, fill=1, stroke=0)
    pdf.setFillColor(brand_yellow)
    pdf.rect(0, height - (6 * mm), width, 6 * mm, fill=1, stroke=0)

    pdf.setFillColor(colors.white)
    pdf.setFont(bold_font, 22)
    pdf.drawString(
        left,
        top - (8 * mm),
        _pdf_shorten_text(pdf, tenant_label, right - left - (70 * mm), bold_font, 22),
    )
    pdf.setFont(regular_font, 10)
    pdf.drawString(left, top - (15 * mm), "Expense Voucher")
    pdf.setFont(regular_font, 9)
    pdf.drawString(
        left,
        top - (22 * mm),
        _pdf_shorten_text(pdf, voucher_no, right - left - (70 * mm), regular_font, 9),
    )

    badge_x = right - (58 * mm)
    pdf.setFillColor(brand_yellow)
    pdf.roundRect(badge_x, top - (18 * mm), 58 * mm, 12 * mm, 3 * mm, fill=1, stroke=0)
    pdf.setFillColor(brand_black)
    pdf.setFont(bold_font, 10)
    pdf.drawCentredString(badge_x + (29 * mm), top - (10.8 * mm), "EXPENSE")
    pdf.setFillColor(colors.white)
    pdf.setFont(regular_font, 9)
    pdf.drawRightString(right, top - (24 * mm), expense_date)

    info_top = top - (40 * mm)
    info_height = 54 * mm
    info_width = right - left
    content_x = left + (6 * mm)
    content_width = info_width - (12 * mm)
    column_gap = 10 * mm
    column_width = (content_width - column_gap) / 2
    right_column_x = content_x + column_width + column_gap

    pdf.setFillColor(brand_surface_warm)
    pdf.setStrokeColor(border_color)
    pdf.setLineWidth(1)
    pdf.roundRect(left, info_top - info_height, info_width, info_height, 4 * mm, fill=1, stroke=1)
    pdf.setStrokeColor(brand_yellow)
    pdf.setLineWidth(2)
    pdf.line(left + (6 * mm), info_top - (6 * mm), right - (6 * mm), info_top - (6 * mm))

    pdf.setFillColor(text_main)
    pdf.setFont(bold_font, 11)
    pdf.drawString(content_x, info_top - (11 * mm), "Voucher Details")

    row_one_y = info_top - (18 * mm)
    row_two_y = info_top - (31 * mm)
    row_three_y = info_top - (44 * mm)
    draw_field(content_x, row_one_y, "Voucher No", voucher_no, column_width)
    draw_field(
        right_column_x,
        row_one_y,
        "Expense Date",
        expense_date,
        column_width,
        value_font=regular_font,
    )
    draw_field(content_x, row_two_y, "Title", title, column_width, max_lines=1)
    draw_field(
        right_column_x,
        row_two_y,
        "Generated By",
        generated_by_name,
        column_width,
        value_font=regular_font,
        value_size=9.5,
    )
    draw_field(content_x, row_three_y, "Receiver", receiver, column_width, value_font=regular_font)
    draw_field(
        right_column_x,
        row_three_y,
        "Category",
        category_name,
        column_width,
        value_font=regular_font,
    )

    summary_top = info_top - info_height - (12 * mm)
    pdf.setFillColor(text_main)
    pdf.setFont(bold_font, 11)
    pdf.drawString(left, summary_top, "Expense Summary")

    table_top = summary_top - (6 * mm)
    table_width = right - left
    item_col = 80 * mm
    branch_col = 40 * mm
    files_col = 28 * mm
    amount_col = table_width - item_col - branch_col - files_col
    header_height = 10 * mm
    row_line_height = 4.2 * mm

    item_lines = _pdf_wrap_text(pdf, title, item_col - (8 * mm), bold_font, 10, max_lines=2)
    branch_lines = _pdf_wrap_text(
        pdf, branch_name, branch_col - (6 * mm), regular_font, 9.5, max_lines=2
    )
    body_line_count = max(len(item_lines), len(branch_lines), 1)
    body_height = max(15 * mm, (body_line_count * row_line_height) + (6 * mm))
    total_height = 11 * mm
    table_height = header_height + body_height + total_height
    table_bottom = table_top - table_height

    pdf.setFillColor(brand_surface)
    pdf.setStrokeColor(border_color)
    pdf.setLineWidth(1)
    pdf.roundRect(left, table_bottom, table_width, table_height, 4 * mm, fill=1, stroke=1)

    pdf.setFillColor(brand_black)
    pdf.roundRect(left, table_top - header_height, table_width, header_height, 4 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont(bold_font, 9)
    header_y = table_top - (6.5 * mm)
    pdf.drawString(left + (4 * mm), header_y, "ITEM")
    pdf.drawString(left + item_col + (3 * mm), header_y, "BRANCH")
    pdf.drawString(left + item_col + branch_col + (3 * mm), header_y, "FILES")
    pdf.drawRightString(right - (4 * mm), header_y, "AMOUNT")

    body_y = table_top - header_height - (6 * mm)
    _pdf_draw_lines(
        pdf,
        left + (4 * mm),
        body_y,
        item_lines,
        bold_font,
        10,
        text_main,
        row_line_height,
    )
    _pdf_draw_lines(
        pdf,
        left + item_col + (3 * mm),
        body_y,
        branch_lines,
        regular_font,
        9.5,
        text_main,
        row_line_height,
    )
    pdf.setFillColor(text_main)
    pdf.setFont(regular_font, 9.5)
    pdf.drawString(
        left + item_col + branch_col + (3 * mm),
        body_y - (row_line_height * 0.2),
        str(attachment_count),
    )
    pdf.setFont(bold_font, 10)
    pdf.drawRightString(right - (4 * mm), body_y - (row_line_height * 0.2), amount)

    pdf.setFillColor(brand_yellow)
    pdf.rect(left, table_bottom, table_width, total_height, fill=1, stroke=0)
    pdf.setFillColor(brand_black)
    pdf.setFont(bold_font, 10)
    pdf.drawString(left + (4 * mm), table_bottom + (4 * mm), "TOTAL")
    pdf.drawRightString(right - (4 * mm), table_bottom + (4 * mm), amount)

    notes_top = table_bottom - (14 * mm)
    pdf.setFillColor(text_main)
    pdf.setFont(bold_font, 11)
    pdf.drawString(left, notes_top, "Notes")
    note_lines = _pdf_wrap_text(
        pdf, description, right - left, regular_font, 9.5, max_lines=4
    )
    _pdf_draw_lines(
        pdf,
        left,
        notes_top - (6 * mm),
        note_lines,
        regular_font,
        9.5,
        text_muted,
        4.2 * mm,
    )

    pdf.setFillColor(text_muted)
    pdf.setFont(regular_font, 8)
    pdf.drawCentredString(
        width / 2,
        14 * mm,
        "This document is an expense voucher for internal accounting records.",
    )

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
