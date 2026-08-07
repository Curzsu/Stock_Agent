"""
PDF Styles Module - Professional Jinja2 HTML template for financial analysis reports.

Industry-standard approach:
  1. Parse MD report into structured sections (title, summary, analysis chapters)
  2. Fill data into a professional research report HTML template via Jinja2
  3. Render HTML to PDF

Design reference: Institutional Research Report Style (Goldman Sachs / JP Morgan / McKinsey)
  - Full-bleed dark navy cover with strong visual hierarchy
  - Minimalist, typography-driven design inspired by The Economist
  - Left-aligned bold title with generous whitespace
  - Structured info grid with clean separators
  - Accent lines and geometric details for authority
  - Compact body layout without forced page breaks between sections
  - Chinese numbering for major sections (一、二、三...)
  - Clean section headers with bottom border, no background fill
  - Tight line spacing for information density
  - Color palette: deep navy (#0c1e3a), steel blue (#1a3a6b), accent gold (#c9a84c)
"""

import re
from typing import Dict, List, Any


# Chinese number mapping for section numbering
_CN_NUMS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
            "十一", "十二", "十三", "十四", "十五",
            "十六", "十七", "十八", "十九", "二十",
            "二十一", "二十二", "二十三", "二十四", "二十五"]


# ============================================================================
# Shared title parser -- handles sh./sz./bare code formats
# ============================================================================

# Matches a stock code in parentheses, with optional sh./sz. exchange prefix.
# Covers: (sh.601998) / (sz.002594) / (601998) / （600519）
_STOCK_CODE_RE = re.compile(r'[（(](?:s[hz]\.)?(\d{5,6})[)）]')


def extract_title_info(raw_title: str) -> Dict[str, str]:
    """Extract company_name and stock_code from a report H1 title.

    Handles the three real-world title formats produced by the system:
      - "中信银行(sh.601998) 综合分析报告"   (sh. prefix)
      - "比亚迪(sz.002594) 综合分析报告"     (sz. prefix)
      - "平安银行(000001) 综合分析报告"      (bare code)

    Returns a dict with 'company_name' and 'stock_code' (empty strings if not found).
    """
    code_match = _STOCK_CODE_RE.search(raw_title)
    stock_code = code_match.group(1) if code_match else ""

    # Strip the parenthesized code (with any prefix) and the report-type suffix
    company_name = _STOCK_CODE_RE.sub('', raw_title)
    company_name = company_name.replace('综合分析报告', '').strip()

    return {"company_name": company_name, "stock_code": stock_code}


# ============================================================================
# MD -> Structured Data Parser
# ============================================================================

def parse_md_to_sections(md_content: str) -> Dict[str, Any]:
    """
    Parse a FINEX markdown report into structured sections for template filling.
    """
    import markdown as md_lib

    # Extract H1 title
    h1_match = re.search(r'^#\s+(.+)$', md_content, re.MULTILINE)
    raw_title = h1_match.group(1).strip() if h1_match else "金融分析报告"

    # Extract company_name / stock_code via the shared parser
    info = extract_title_info(raw_title)
    company_name = info["company_name"]
    stock_code = info["stock_code"]

    # Split into sections by ## headers
    parts = re.split(r'^##\s+', md_content, flags=re.MULTILINE)

    sections = []
    for i, part in enumerate(parts):
        if i == 0:
            continue

        lines = part.split('\n', 1)
        heading = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""

        body = body.replace('[TOC]', '')
        if not heading:
            continue

        body_html = md_lib.markdown(body, extensions=['tables', 'fenced_code', 'nl2br'])

        # Chinese number for this section
        cn_num = _CN_NUMS[len(sections)] if len(sections) < len(_CN_NUMS) else str(len(sections) + 1)

        sections.append({
            "number": len(sections) + 1,
            "cn_number": cn_num,
            "heading": heading,
            "body_html": body_html,
        })

    return {
        "company_name": company_name,
        "stock_code": stock_code,
        "raw_title": raw_title,
        "sections": sections,
    }


# ============================================================================
# Jinja2 HTML Template - Institutional Research Style
# ============================================================================

REPORT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<title>{{ company_name }} ({{ stock_code }}) 综合分析报告</title>
<style>
/* ================================================================
   RESET & BASE
   ================================================================ */
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: "SimSun", "STSong-Light", "MicrosoftYaHei", "SimHei", sans-serif;
    font-size: 9.5pt;
    line-height: 1.65;
    color: #333333;
}

@page { size: A4; margin: 1.5cm 1.8cm 1.5cm 1.8cm; }

/* Cover page uses inline styles with <table>-based layout for xhtml2pdf compatibility */

/* ================================================================
   TABLE OF CONTENTS
   ================================================================ */
.toc-page {
    page-break-after: always;
}

.toc-header {
    font-size: 13pt;
    font-weight: bold;
    color: #1a3a6b;
    padding-bottom: 4px;
    border-bottom: 2px solid #1a3a6b;
    margin-bottom: 0.5cm;
}

.toc-item {
    padding: 5px 0;
    font-size: 9.5pt;
    color: #333333;
    border-bottom: 1px dotted #cccccc;
}

.toc-num {
    font-weight: bold;
    color: #1a3a6b;
    margin-right: 8px;
}

.toc-dots {
    color: #bbbbbb;
    letter-spacing: 1px;
}

/* ================================================================
   SECTION HEADINGS - Clean, no background fill
   ================================================================ */

/* H2: Major section - Chinese number + heading with bottom border */
h2 {
    font-size: 12pt;
    font-weight: bold;
    color: #1a3a6b;
    border-bottom: 1.5px solid #1a3a6b;
    padding-bottom: 3px;
    margin-top: 0.5cm;
    margin-bottom: 0.25cm;
}

/* H3: Sub-section - left accent bar */
h3 {
    font-size: 10pt;
    font-weight: bold;
    color: #1a3a6b;
    border-left: 3px solid #1a3a6b;
    padding-left: 6px;
    margin-top: 0.3cm;
    margin-bottom: 0.15cm;
}

/* H4: Sub-sub-section - plain bold */
h4 {
    font-size: 9.5pt;
    font-weight: bold;
    color: #333333;
    margin-top: 0.2cm;
    margin-bottom: 0.1cm;
}

/* ================================================================
   BODY TEXT
   ================================================================ */
p {
    margin-bottom: 0.15cm;
    text-align: justify;
    color: #333333;
    font-size: 9.5pt;
    line-height: 1.65;
}

strong, b {
    font-weight: bold;
    color: #1a3a6b;
}

em, i {
    font-style: italic;
    color: #555555;
}

/* ================================================================
   LISTS - Compact
   ================================================================ */
ul, ol {
    margin: 0.1cm 0 0.15cm 0.6cm;
    padding-left: 0.4cm;
    color: #333333;
    font-size: 9.5pt;
}

li {
    margin-bottom: 0.05cm;
    line-height: 1.6;
}

/* ================================================================
   TABLES - Body content tables only (cover uses inline styles)
   ================================================================ */
thead th {
    background: #1a3a6b;
    color: #ffffff;
    padding: 4px 6px;
    text-align: left;
    font-weight: bold;
    font-size: 8pt;
    border: 1px solid #1a3a6b;
}

tbody td {
    padding: 3px 6px;
    border: 1px solid #dddddd;
    color: #333333;
    font-size: 8.5pt;
}

tbody tr:nth-child(even) {
    background: #f5f6f8;
}

/* ================================================================
   BLOCKQUOTES - Insight/highlight boxes
   ================================================================ */
blockquote {
    border-left: 3px solid #c9a84c;
    background: #faf8f0;
    padding: 6px 10px;
    margin: 0.15cm 0;
    font-size: 9pt;
    color: #444444;
}

/* ================================================================
   HR - Section dividers
   ================================================================ */
hr {
    border: none;
    height: 1px;
    background: #dddddd;
    margin: 0.3cm 0;
}

/* ================================================================
   CODE
   ================================================================ */
code {
    font-family: "Consolas", monospace;
    background: #f4f4f4;
    padding: 1px 3px;
    font-size: 8pt;
}

pre {
    background: #f5f5f5;
    border: 1px solid #dddddd;
    color: #333333;
    padding: 8px 10px;
    font-size: 8pt;
    line-height: 1.4;
    margin: 0.15cm 0;
}

pre code { background: none; color: inherit; padding: 0; }

/* ================================================================
   SECTION NUMBER
   ================================================================ */
.sec-num {
    font-weight: bold;
    margin-right: 4px;
}

/* ================================================================
   FOOTER DISCLAIMER
   ================================================================ */
.report-footer {
    margin-top: 0.6cm;
    padding-top: 0.3cm;
    border-top: 1px solid #cccccc;
    font-size: 7pt;
    color: #999999;
    line-height: 1.6;
}

.report-footer b {
    color: #666666;
    font-size: 7pt;
}
</style>
</head>
<body>

<!-- ======================== COVER ======================== -->
<div style="page-break-after: always;">
<table width="100%" cellpadding="0" cellspacing="0" border="0">
    <!-- Top accent bar -->
    <tr><td bgcolor="#1a3a6b" style="height: 6px; font-size: 1px; line-height: 1px;">&nbsp;</td></tr>
    <!-- Top Bar: Brand Identity -->
    <tr>
        <td style="padding: 28px 45px 12px 45px;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                    <td style="vertical-align: middle;">
                        <p style="color: #1a3a6b; font-size: 15pt; font-weight: bold; margin: 0; font-family: MicrosoftYaHei, SimHei, sans-serif;">FINEX RESEARCH</p>
                        <p style="color: #8899aa; font-size: 7.5pt; margin: 3px 0 0 0;">FINANCIAL INTELLIGENCE &middot; AI AGENT SYSTEM</p>
                    </td>
                    <td style="text-align: right; vertical-align: middle; width: 160px;">
                        <p style="color: #8899aa; font-size: 7pt; margin: 0;">EQUITY ANALYSIS</p>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    <!-- Separator -->
    <tr>
        <td style="padding: 0 45px;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr><td bgcolor="#cccccc" style="height: 1px; font-size: 1px; line-height: 1px;">&nbsp;</td></tr>
            </table>
        </td>
    </tr>
    <!-- Hero Title Area -->
    <tr>
        <td style="padding: 60px 45px 40px 45px;">
            <!-- Gold accent bar -->
            <table cellpadding="0" cellspacing="0" border="0" style="width: 45px;">
                <tr><td bgcolor="#c9a84c" style="height: 4px; font-size: 1px; line-height: 1px;">&nbsp;</td></tr>
            </table>
            <!-- Main title -->
            <h1 style="font-size: 30pt; color: #1a3a6b; font-weight: bold; margin: 20px 0 5px 0; font-family: MicrosoftYaHei, SimHei, sans-serif;">{{ company_name or "金融分析报告" }}</h1>
            <!-- Subtitle -->
            <p style="font-size: 14pt; color: #555555; margin: 10px 0 0 0;">综合分析报告</p>
            <!-- Stock code badge -->
            {% if stock_code %}
            <table cellpadding="0" cellspacing="0" border="0" style="margin-top: 18px;">
                <tr><td style="border: 1px solid #1a3a6b; padding: 5px 16px; color: #1a3a6b; font-size: 10pt; font-family: Consolas, monospace;">{{ stock_code }}</td></tr>
            </table>
            {% endif %}
        </td>
    </tr>
    <!-- Info Grid -->
    <tr>
        <td style="padding: 0 45px;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <!-- Top separator -->
                <tr><td colspan="2" bgcolor="#cccccc" style="height: 1px; font-size: 1px; line-height: 1px;">&nbsp;</td></tr>
                <!-- Row 1 -->
                <tr>
                    <td width="50%" style="padding: 12px 10px 8px 0;">
                        <p style="color: #999999; font-size: 7pt; margin: 0 0 2px 0;">分析日期 DATE</p>
                        <p style="color: #333333; font-size: 9pt; margin: 0;">{{ analysis_date }}</p>
                    </td>
                    <td width="50%" style="padding: 12px 0 8px 10px;">
                        <p style="color: #999999; font-size: 7pt; margin: 0 0 2px 0;">报告类型 TYPE</p>
                        <p style="color: #333333; font-size: 9pt; margin: 0;">综合分析报告</p>
                    </td>
                </tr>
                <!-- Row 2 -->
                <tr>
                    <td style="padding: 5px 10px 5px 0;">
                        <p style="color: #999999; font-size: 7pt; margin: 0 0 2px 0;">研究机构 INSTITUTION</p>
                        <p style="color: #333333; font-size: 9pt; margin: 0;">FINEX Financial Intelligence</p>
                    </td>
                    <td style="padding: 5px 0 5px 10px;">
                        <p style="color: #999999; font-size: 7pt; margin: 0 0 2px 0;">数据截止 DATA AS OF</p>
                        <p style="color: #333333; font-size: 9pt; margin: 0;">{{ analysis_date }}</p>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    <!-- Spacer -->
    <tr><td style="height: 130px; font-size: 1px;">&nbsp;</td></tr>
    <!-- Bottom Disclaimer -->
    <tr>
        <td style="padding: 0 45px 25px 45px;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr><td bgcolor="#cccccc" style="height: 1px; font-size: 1px; line-height: 1px;">&nbsp;</td></tr>
            </table>
            <p style="color: #999999; font-size: 6.5pt; margin-top: 12px; line-height: 1.7;">
                本报告由 FINEX 金融分析智能体系统自动生成，仅供学术研究和投资参考之用，不构成任何投资建议。
                投资有风险，入市需谨慎。过往业绩不代表未来表现。本报告中的分析、观点和预测均基于公开市场数据，
                FINEX 对因使用本报告造成的任何直接或间接损失不承担责任。
            </p>
        </td>
    </tr>
    <!-- Gold Bottom Strip -->
    <tr><td bgcolor="#c9a84c" style="height: 5px; font-size: 1px; line-height: 1px;">&nbsp;</td></tr>
</table>
</div>

<!-- ======================== TOC ======================== -->
<div class="toc-page">
    <div class="toc-header">目 录</div>
    {% for sec in sections %}
    <div class="toc-item">
        <span class="toc-num">{{ sec.cn_number }}、</span>{{ sec.heading }}
    </div>
    {% endfor %}
</div>

<!-- ======================== BODY - Continuous, no page breaks between sections ======================== -->
{% for sec in sections %}
<h2><span class="sec-num">{{ sec.cn_number }}、</span>{{ sec.heading }}</h2>
{{ sec.body_html }}
{% endfor %}

<!-- ======================== FOOTER ======================== -->
<div class="report-footer">
    <b>免责声明</b><br/>
    本报告由 FINEX 金融分析智能体系统基于公开市场数据自动生成，仅供学术研究和投资参考之用。
    报告中的分析、观点和预测不构成任何形式的投资建议。投资者应基于自身判断做出投资决策，
    并承担相应风险。FINEX 对因使用本报告造成的任何直接或间接损失不承担责任。<br/><br/>
    <b>数据来源</b>：Baostock、公开市场数据 &nbsp;&nbsp; <b>生成时间</b>：{{ gen_time }} &nbsp;&nbsp; <b>FINEX Financial Intelligence</b>
</div>

</body>
</html>"""


# ============================================================================
# Renderer
# ============================================================================

def render_report_html(
    md_content: str,
    company_name: str = "",
    stock_code: str = "",
    analysis_date: str = "",
) -> str:
    """
    Parse MD -> structured data -> Jinja2 template -> HTML string.
    """
    from jinja2 import Template
    from datetime import datetime

    data = parse_md_to_sections(md_content)

    context = {
        "company_name": company_name or data["company_name"],
        "stock_code": stock_code or data["stock_code"],
        "analysis_date": analysis_date or datetime.now().strftime("%Y-%m-%d"),
        "gen_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sections": data["sections"],
    }

    template = Template(REPORT_TEMPLATE)
    return template.render(**context)
