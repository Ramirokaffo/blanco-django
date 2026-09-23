"""
Génération de factures au format PDF.

reportlab est pur Python (aucune bibliothèque système comme Cairo/Pango),
contrairement à weasyprint/xhtml2pdf : c'est le seul choix qui ne complique
pas le packaging PyInstaller de l'application Windows (voir blanco.spec).
"""

from io import BytesIO

from django.utils.translation import gettext as _

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def _format_amount(value, currency):
    return f"{value or 0:,.0f} {currency}".replace(',', ' ')


class InvoicePdfService:

    @staticmethod
    def build_pdf(invoice, system_settings) -> bytes:
        """Construit le PDF d'une facture et retourne son contenu binaire."""
        sale = invoice.sale
        currency = system_settings.currency_symbol or 'FCFA'

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=20 * mm, rightMargin=20 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
            title=invoice.invoice_number,
        )
        styles = getSampleStyleSheet()
        normal = styles['Normal']
        footer_style = ParagraphStyle('Footer', parent=normal, alignment=TA_CENTER, textColor=colors.grey)

        elements = []

        elements.append(Paragraph(system_settings.company_name or _("Facture"), styles['Title']))
        if system_settings.company_address:
            elements.append(Paragraph(system_settings.company_address, normal))
        contact_bits = [b for b in [system_settings.company_phone, system_settings.company_email] if b]
        if contact_bits:
            elements.append(Paragraph(' · '.join(contact_bits), normal))
        legal_bits = []
        if system_settings.tax_id:
            legal_bits.append(_("NIF : %(value)s") % {'value': system_settings.tax_id})
        if system_settings.trade_register:
            legal_bits.append(_("RCCM : %(value)s") % {'value': system_settings.trade_register})
        if legal_bits:
            elements.append(Paragraph(' · '.join(legal_bits), normal))
        elements.append(Spacer(1, 10 * mm))

        elements.append(Paragraph(_("Facture %(number)s") % {'number': invoice.invoice_number}, styles['Heading2']))
        meta_rows = [[_("Date"), invoice.invoice_date.strftime('%d/%m/%Y')]]
        if invoice.due_date:
            meta_rows.append([_("Échéance"), invoice.due_date.strftime('%d/%m/%Y')])
        if sale.client:
            meta_rows.append([_("Client"), sale.client.get_full_name()])
        meta_table = Table(meta_rows, colWidths=[35 * mm, 100 * mm])
        meta_table.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 10)]))
        elements.append(meta_table)
        elements.append(Spacer(1, 6 * mm))

        data = [[_("Produit"), _("Qté"), _("Prix unitaire"), _("Total")]]
        lines = sale.sale_products.filter(
            delete_at__isnull=True, quantity__gt=0,
        ).select_related('product')
        for line in lines:
            data.append([
                line.product.name,
                str(line.quantity),
                _format_amount(line.unit_price, currency),
                _format_amount(line.get_subtotal(), currency),
            ])
        items_table = Table(data, colWidths=[80 * mm, 20 * mm, 35 * mm, 35 * mm], repeatRows=1)
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 4 * mm))

        total_table = Table(
            [[_("Total TTC"), _format_amount(sale.total, currency)]],
            colWidths=[135 * mm, 35 * mm],
        )
        total_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('LINEABOVE', (0, 0), (-1, 0), 1, colors.black),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(total_table)

        if system_settings.receipt_footer:
            elements.append(Spacer(1, 10 * mm))
            elements.append(Paragraph(system_settings.receipt_footer, footer_style))

        doc.build(elements)
        return buffer.getvalue()
