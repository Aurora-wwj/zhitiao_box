"""Optional document generator; requires reportlab, not an Agent dependency."""
from html import escape
from pathlib import Path

def main():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    root = Path(__file__).resolve().parent
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    body = ParagraphStyle('body', fontName='STSong-Light', fontSize=11, leading=18, wordWrap='CJK')
    heading = ParagraphStyle('heading', parent=body, fontSize=14, leading=22, spaceBefore=12, keepWithNext=True)
    story = []
    for block in (root/'design_report.md').read_text(encoding='utf-8').split('\n\n'):
        block = block.strip()
        if not block:
            continue
        is_heading = block.startswith('#')
        story.append(Paragraph(escape(block.lstrip('# ').replace('\n', ' ')), heading if is_heading else body))
        story.append(Spacer(1, 9))
    SimpleDocTemplate(str(root/'design_report.pdf'), pagesize=A4, title='智调盒设计报告整理初稿',
                       author='Zhitiaohe contributors').build(story)

if __name__ == '__main__':
    main()
