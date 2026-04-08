"""
PDF Styles Module - Professional CSS template for financial analysis reports.

This module provides the CSS stylesheet and HTML wrapper used by pdf_converter.py
to generate authoritative, investment-bank-quality PDF reports.

Separate from conversion logic so visual design can be iterated without touching Python code.

Provides two CSS variants:
- PDF_CSS_WEASYPRINT: Full-featured CSS for WeasyPrint (with @page sub-rules)
- PDF_CSS_XHTML2PDF: Compatible CSS for xhtml2pdf (simple @page only)
"""

# ============================================================================
# @page rules for each engine
# ============================================================================

# Full @page for WeasyPrint - supports sub-rules like @top-left, @bottom-center etc.
_PAGE_CSS_WEASYPRINT = """
@page {
    size: A4;
    margin: 2.2cm 2cm 2.5cm 2cm;

    @top-left {
        content: "FINEX Research";
        font-size: 8pt;
        color: #888888;
        font-family: "Noto Sans SC", "Microsoft YaHei", "SimSun", sans-serif;
    }
    @top-right {
        content: "Confidential";
        font-size: 8pt;
        color: #888888;
        font-family: "Noto Sans SC", "Microsoft YaHei", "SimSun", sans-serif;
    }
    @bottom-center {
        content: counter(page);
        font-size: 9pt;
        color: #555555;
        font-family: "Noto Sans SC", "Microsoft YaHei", "SimSun", sans-serif;
    }
    @bottom-right {
        content: "FINEX | Financial Intelligence";
        font-size: 7pt;
        color: #999999;
        font-family: "Noto Sans SC", "Microsoft YaHei", "SimSun", sans-serif;
    }
}

@page :first {
    margin-top: 0;
    margin-bottom: 0;
    @top-left { content: none; }
    @top-right { content: none; }
    @bottom-center { content: none; }
    @bottom-right { content: none; }
}"""

# Compatible @page for xhtml2pdf - minimal, no sub-rules
_PAGE_CSS_XHTML2PDF = """
@page {
    size: A4;
    margin: 2cm;
}
"""


def _build_font_face_css() -> str:
    """
    Build @font-face declarations using absolute file paths to system Chinese fonts.

    xhtml2pdf requires @font-face with src:url() pointing to real font files.
    Without this, all CJK characters render as 'n' or blank squares.
    """
    import os
    import platform

    # Font search locations by OS
    if platform.system() == "Windows":
        font_dir = r"C:\Windows\Fonts"
    elif platform.system() == "Darwin":  # macOS
        font_dir = "/System/Library/Fonts"
    else:  # Linux
        font_dir = "/usr/share/fonts"

    # (filename, css_font_name, weight)
    font_defs = [
        ("simhei.ttf",  "SimHei", "bold"),
        ("simsun.ttc",  "SimSun", "normal"),
        ("simfang.ttf", "SimFang", "normal"),
        ("simkai.ttf",  "SimKai", "normal"),
        ("msyh.ttc",    "MicrosoftYaHei", "normal"),
        ("msyhbd.ttc",  "MicrosoftYaHei", "bold"),
        ("NotoSansSC-VF.ttf", "NotoSansSC", "normal"),
        ("STSong.ttf",  "STSong", "normal"),
    ]

    css_parts = []
    for filename, name, weight in font_defs:
        path = os.path.join(font_dir, filename)
        if os.path.exists(path):
            # xhtml2pdf needs forward slashes in URL paths, even on Windows
            url_path = path.replace("\\", "/")
            css_parts.append(
                f'@font-face {{ font-family: "{name}"; src: url("{url_path}"); '
                f'font-weight: {weight}; }}'
            )

    return "\n".join(css_parts)

# ============================================================================
# Shared body CSS (works with both engines)
# ============================================================================

_BODY_CSS = """
/* ========================================
   BASE TYPOGRAPHY
   ======================================== */

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: "SimSun", "SimHei", "Microsoft YaHei", "Noto Sans SC", sans-serif;
    font-size: 10.5pt;
    line-height: 1.75;
    color: #1a1a1a;
}

/* ========================================
   COVER PAGE
   ======================================== */

.cover-page {
    page-break-after: always;
    padding: 3cm 2cm;
    text-align: center;
}

.cover-top-bar {
    width: 100%;
    height: 6px;
    background: #c9a227;
    margin-bottom: 2cm;
}

.cover-brand {
    margin-bottom: 1.5cm;
}

.cover-brand-mark {
    font-size: 14pt;
    font-weight: bold;
    color: #c9a227;
    border: 2px solid #c9a227;
    padding: 4px 10px;
    display: inline-block;
}

.cover-brand-name {
    font-size: 11pt;
    font-weight: 600;
    color: #333333;
    text-transform: uppercase;
    margin-left: 12px;
}

.cover-divider {
    width: 80px;
    height: 3px;
    background: #c9a227;
    margin: 0 auto 1.5cm;
}

.cover-title {
    font-size: 28pt;
    font-weight: bold;
    color: #0a0a0a;
    line-height: 1.3;
    margin-bottom: 0.6cm;
}

.cover-subtitle {
    font-size: 14pt;
    color: #666666;
    margin-bottom: 1.5cm;
    font-weight: 400;
}

.cover-meta-table {
    width: 320px;
    margin: 0 auto;
    border-collapse: collapse;
}

.cover-meta-table td {
    padding: 6px 16px;
    font-size: 9.5pt;
    border-bottom: 1px solid #e0e0e0;
}

.cover-meta-table td:first-child {
    color: #888888;
    font-weight: 500;
    width: 100px;
    text-align: left;
}

.cover-meta-table td:last-child {
    color: #1a1a1a;
    font-weight: bold;
    text-align: left;
}

.cover-disclaimer {
    font-size: 7pt;
    color: #aaaaaa;
    line-height: 1.6;
    max-width: 500px;
    margin: 1.5cm auto 0;
}

/* ========================================
   TABLE OF CONTENTS
   ======================================== */

.toc-page {
    page-break-after: always;
    padding-top: 1cm;
}

.toc-title {
    font-size: 18pt;
    font-weight: bold;
    color: #0a0a0a;
    margin-bottom: 0.8cm;
    padding-bottom: 8px;
    border-bottom: 3px solid #c9a227;
}

.toc-list {
    list-style: none;
    padding: 0;
}

.toc-item {
    padding: 8px 0;
    border-bottom: 1px dotted #d0d0d0;
    font-size: 10.5pt;
}

.toc-item-number {
    color: #c9a227;
    font-weight: bold;
    margin-right: 12px;
}

.toc-item-title {
    color: #1a1a1a;
    font-weight: 500;
}

/* ========================================
   SECTION HEADINGS
   ======================================== */

h1 {
    font-size: 22pt;
    font-weight: bold;
    color: #0a0a0a;
    margin: 0;
    padding: 0;
}

h2 {
    font-size: 15pt;
    font-weight: bold;
    color: #0a0a0a;
    margin-top: 1.2cm;
    margin-bottom: 0.4cm;
    padding-bottom: 6px;
    border-bottom: 2.5px solid #c9a227;
}

h2 .section-number {
    color: #c9a227;
    margin-right: 8px;
    font-weight: bold;
}

h3 {
    font-size: 12pt;
    font-weight: bold;
    color: #333333;
    margin-top: 0.6cm;
    margin-bottom: 0.3cm;
}

h4 {
    font-size: 10.5pt;
    font-weight: bold;
    color: #444444;
    margin-top: 0.4cm;
    margin-bottom: 0.2cm;
}

/* ========================================
   BODY CONTENT
   ======================================== */

p {
    margin-bottom: 0.35cm;
    text-align: justify;
    orphans: 3;
    widows: 3;
}

strong, b {
    font-weight: bold;
    color: #0a0a0a;
}

em, i {
    font-style: italic;
    color: #333333;
}

/* ========================================
   LISTS
   ======================================== */

ul, ol {
    margin: 0.3cm 0 0.4cm 0.6cm;
    padding-left: 0.5cm;
}

li {
    margin-bottom: 0.15cm;
    line-height: 1.65;
}

/* ========================================
   TABLES
   ======================================== */

table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.5cm 0;
    font-size: 9.5pt;
}

thead th {
    background: #0a0a0a;
    color: #ffffff;
    padding: 8px 12px;
    text-align: left;
    font-weight: bold;
    font-size: 9pt;
}

tbody td {
    padding: 7px 12px;
    border-bottom: 1px solid #e5e5e5;
}

tbody tr:nth-child(even) {
    background: #fafafa;
}

/* ========================================
   HIGHLIGHT BOXES
   ======================================== */

blockquote {
    border-left: 4px solid #c9a227;
    background: #fdfcf8;
    padding: 12px 16px;
    margin: 0.4cm 0;
    font-size: 10pt;
    color: #333333;
}

/* ========================================
   HORIZONTAL RULES
   ======================================== */

hr {
    border: none;
    height: 1px;
    background: #c9a227;
    margin: 0.8cm 0;
}

/* ========================================
   CODE BLOCKS
   ======================================== */

code {
    font-family: "Consolas", "Source Code Pro", monospace;
    background: #f5f5f5;
    padding: 1px 5px;
    font-size: 9pt;
    color: #c9a227;
}

pre {
    background: #1a1a1a;
    color: #e5e5e5;
    padding: 14px 18px;
    font-size: 8.5pt;
    line-height: 1.5;
    margin: 0.4cm 0;
}

pre code {
    background: none;
    padding: 0;
    color: inherit;
}

/* ========================================
   FOOTER DISCLAIMER (last page)
   ======================================== */

.report-footer {
    margin-top: 1.5cm;
    padding-top: 0.6cm;
    border-top: 2px solid #c9a227;
    font-size: 8pt;
    color: #888888;
    line-height: 1.7;
}

.report-footer strong {
    color: #555555;
    font-size: 8.5pt;
}
"""


def get_css_for_engine(engine: str = "xhtml2pdf") -> str:
    """Return the appropriate CSS for the given PDF engine."""
    if engine == "weasyprint":
        return _PAGE_CSS_WEASYPRINT + _BODY_CSS
    else:
        # @font-face is injected at render time by pdf_converter._render_with_xhtml2pdf
        return _PAGE_CSS_XHTML2PDF + _BODY_CSS


def get_report_html(md_content: str, company_name: str = "", stock_code: str = "",
                    analysis_date: str = "", engine: str = "xhtml2pdf") -> str:
    """
    Wrap Markdown content in a professional HTML template for PDF rendering.

    Args:
        md_content: Raw Markdown content from the report
        company_name: Company name for the cover page
        stock_code: Stock code for the cover page
        analysis_date: Date string for the cover page
        engine: PDF engine ("xhtml2pdf" or "weasyprint")

    Returns:
        Complete HTML string ready for PDF rendering
    """
    import markdown as md_lib
    from datetime import datetime
    import re

    # Get the right CSS for the engine
    css = get_css_for_engine(engine)

    # Convert Markdown to HTML
    md_extensions = ['tables', 'fenced_code', 'nl2br']
    body_html = md_lib.markdown(md_content, extensions=md_extensions)

    # Extract sections for TOC
    sections = re.findall(r'^##\s+(.+)$', md_content, re.MULTILINE)
    section_number = 1
    toc_items = []
    for section in sections:
        toc_items.append(f"""
        <div class="toc-item">
            <span class="toc-item-number">{section_number:02d}</span>
            <span class="toc-item-title">{section}</span>
        </div>""")
        section_number += 1

    toc_html = "\n".join(toc_items)

    # Replace h2 headers with numbered versions
    counter = [0]
    def add_section_number(match):
        counter[0] += 1
        return f'<h2><span class="section-number">{counter[0]:02d}</span>{match.group(1)}</h2>'
    body_html = re.sub(r'<h2>(.+?)</h2>', add_section_number, body_html)

    # Remove the first h1 from body (it's shown on the cover page instead)
    body_html = re.sub(r'^<h1>.*?</h1>\s*', '', body_html, count=1, flags=re.DOTALL)

    # Also remove [TOC] if present
    body_html = body_html.replace('[TOC]', '')

    # Build cover page
    now = datetime.now()
    date_display = analysis_date or now.strftime("%Y-%m-%d")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8"/>
    <title>{company_name} ({stock_code}) 综合分析报告</title>
    <style>{css}</style>
</head>
<body>
    <!-- COVER PAGE -->
    <div class="cover-page">
        <div class="cover-top-bar"></div>

        <div class="cover-brand">
            <span class="cover-brand-mark">FX</span>
            <span class="cover-brand-name">FINEX Research</span>
        </div>

        <div class="cover-divider"></div>
        <h1 class="cover-title">{company_name or '金融分析报告'}</h1>
        <p class="cover-subtitle">{'(' + stock_code + ') ' if stock_code else ''}综合分析报告</p>

        <table class="cover-meta-table">
            <tr><td>分析日期</td><td>{date_display}</td></tr>
            <tr><td>报告类型</td><td>综合分析报告</td></tr>
            <tr><td>分析师</td><td>FINEX AI Agent System</td></tr>
            <tr><td>版本</td><td>V2.0</td></tr>
        </table>

        <p class="cover-disclaimer">
            本报告由 FINEX 金融分析智能体系统自动生成，仅供研究参考，不构成任何投资建议。
            投资有风险，入市需谨慎。过往业绩不代表未来表现。
        </p>
    </div>

    <!-- TABLE OF CONTENTS -->
    <div class="toc-page">
        <div class="toc-title">目 录</div>
        <div class="toc-list">
            {toc_html}
        </div>
    </div>

    <!-- REPORT BODY -->
    <div class="report-body">
        {body_html}

        <!-- FOOTER DISCLAIMER -->
        <div class="report-footer">
            <strong>免责声明</strong><br/>
            本报告由 FINEX 金融分析智能体系统基于公开市场数据自动生成，仅供学术研究和投资参考之用。
            报告中的分析、观点和预测不构成任何形式的投资建议、推荐或承诺。投资者应基于自身判断做出投资决策，
            并承担相应风险。FINEX 对因使用本报告而造成的任何直接或间接损失不承担责任。<br/><br/>
            <strong>数据来源</strong>：Baostock、公开市场数据<br/>
            <strong>报告生成时间</strong>：{now.strftime("%Y-%m-%d %H:%M:%S")}<br/>
            <strong>FINEX Financial Intelligence</strong>
        </div>
    </div>
</body>
</html>"""

    return html
