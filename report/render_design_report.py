"""Optional document generator; requires reportlab, not an Agent dependency."""
from html import escape
from pathlib import Path
import re


def inline(text):
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1（\2）', text)
    return escape(re.sub(r'`([^`]+)`', r'\1', text))

def main():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                    KeepTogether, PageBreak, Preformatted, Table, TableStyle)
    root = Path(__file__).resolve().parent
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    body = ParagraphStyle('body', fontName='STSong-Light', fontSize=11, leading=18, wordWrap='CJK')
    heading = ParagraphStyle('heading', parent=body, fontSize=14, leading=22, spaceBefore=12, keepWithNext=True)
    caption = ParagraphStyle('caption', parent=body, fontSize=9, leading=14, textColor=colors.HexColor('#405873'))
    cell = ParagraphStyle('cell', parent=body, fontSize=9, leading=14)
    code = ParagraphStyle('code', fontName='Courier', fontSize=7.5, leading=10)
    width = A4[0] - 108
    story = []
    lines = (root/'design_report.md').read_text(encoding='utf-8').splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith('```'):
            content = []
            index += 1
            while index < len(lines) and not lines[index].startswith('```'):
                content.append(lines[index])
                index += 1
            story.append(Preformatted('\n'.join(content), code))
            index += 1
        elif line.startswith('|'):
            rows = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                values = [value.strip() for value in lines[index].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', value) for value in values):
                    rows.append([Paragraph(inline(value), cell) for value in values])
                index += 1
            table = Table(rows, colWidths=[width/len(rows[0])]*len(rows[0]), repeatRows=1)
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf1fa')),
                                       ('GRID',(0,0),(-1,-1),.5,colors.HexColor('#d6e0ec')),
                                       ('VALIGN',(0,0),(-1,-1),'TOP'),
                                       ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
            story.append(table)
        elif (match := re.fullmatch(r'!\[(.*?)\]\(([^)]+)\)', line)):
            path = (root / match[2]).resolve(strict=True)
            if not path.is_relative_to(root.parent):
                raise ValueError('Report image must be inside the repository')
            figure = Image(str(path))
            scale = min(width/figure.imageWidth, 300/figure.imageHeight)
            figure.drawWidth = figure.imageWidth*scale
            figure.drawHeight = figure.imageHeight*scale
            story.append(KeepTogether([figure, Spacer(1, 5), Paragraph(inline(match[1]), caption)]))
            index += 1
        elif line.startswith('#'):
            if line == '## 实测截图与证据':
                story.append(PageBreak())
            story.append(Paragraph(inline(line.lstrip('# ')), heading))
            index += 1
        else:
            content = [line]
            index += 1
            while index < len(lines) and lines[index].strip() and not lines[index].startswith(('#','|','```','![')):
                content.append(lines[index].strip())
                index += 1
            story.append(Paragraph(inline(' '.join(content)), body))
        story.append(Spacer(1, 9))
    SimpleDocTemplate(str(root/'design_report.pdf'), pagesize=A4, leftMargin=54, rightMargin=54,
                       topMargin=54, bottomMargin=54, title='智调盒——AI上板摆渡站（整理初稿）',
                       author='Zhitiaohe contributors').build(story)

if __name__ == '__main__':
    main()
