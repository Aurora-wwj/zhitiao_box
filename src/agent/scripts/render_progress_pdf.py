"""Optional docs helper (requires reportlab); not a runtime dependency.

Run from a checkout: python scripts/render_progress_pdf.py
"""

from html import escape
from pathlib import Path
import re


def main():
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

    root = Path(__file__).resolve().parents[1]
    source = root / 'docs/progress-and-roadmap.md'
    target = source.with_suffix('.pdf')
    font = 'STSong-Light'
    pdfmetrics.registerFont(UnicodeCIDFont(font))
    body = ParagraphStyle('body', fontName=font, fontSize=10, leading=15, wordWrap='CJK', spaceAfter=8)
    title = ParagraphStyle('title', parent=body, fontSize=18, leading=24, alignment=TA_CENTER, spaceAfter=17)
    heading = ParagraphStyle('heading', parent=body, fontSize=12.5, leading=18, spaceBefore=10, spaceAfter=8, keepWithNext=True)
    cell = ParagraphStyle('cell', parent=body, fontSize=9, leading=13, spaceAfter=0)
    code = ParagraphStyle('code', parent=body, fontSize=8.5, leading=12, backColor=colors.HexColor('#f2f5f8'), borderPadding=7)

    def clean(value):
        value = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1（\2）', value)
        return escape(value.replace('**', '').replace('`', ''))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#53657a'))
        canvas.drawString(42, 25, 'zhidiao-agent')
        canvas.drawRightString(A4[0]-42, 25, str(document.page))
        canvas.restoreState()

    lines = source.read_text(encoding='utf-8').splitlines()
    story, index = [], 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
        elif line.startswith('```'):
            index += 1
            block = []
            while index < len(lines) and not lines[index].strip().startswith('```'):
                block.append(clean(lines[index])); index += 1
            story.extend([Paragraph('<br/>'.join(block), code), Spacer(1, 9)])
            index += 1
        elif line.startswith('|'):
            rows = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                values = [value.strip() for value in lines[index].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', value) for value in values):
                    rows.append([Paragraph(clean(value), cell) for value in values])
                index += 1
            width = A4[0]-84
            widths = [88, 220, width-308] if len(rows[0]) == 3 else [145, width-145]
            table = LongTable(rows, colWidths=widths, repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dce7f5')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f7fa')]),
                ('LINEBELOW', (0, 0), (-1, -1), .35, colors.HexColor('#d1dae4')),
                ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.extend([table, Spacer(1, 10)])
        elif line.startswith('# '):
            story.append(Paragraph(clean(line[2:]), title)); index += 1
        elif line.startswith('## '):
            story.append(Paragraph(clean(line[3:]), heading)); index += 1
        else:
            paragraph = [line]
            index += 1
            while index < len(lines) and lines[index].strip() and not lines[index].strip().startswith(('#', '|', '```')):
                paragraph.append(lines[index].strip()); index += 1
            story.append(Paragraph(clean(' '.join(paragraph)), body))
    SimpleDocTemplate(str(target), pagesize=A4, rightMargin=42, leftMargin=42, topMargin=40,
                      bottomMargin=42, title=lines[0].removeprefix('# '), author='zhidiao-agent',
                      pageCompression=1).build(story, onFirstPage=footer, onLaterPages=footer)
    print('Generated', target.name, target.stat().st_size, 'bytes')


if __name__ == '__main__':
    main()
