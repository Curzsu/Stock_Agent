"""Prepare lossless Markdown and Eisvogel metadata; theme lives in pdf_templates."""

import os
import re
from dataclasses import dataclass
from datetime import datetime


_STOCK_CODE_RE = re.compile(r"[（(](?:s[hz]\.)?(\d{5,6})[)）]")
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


@dataclass(frozen=True)
class ReportDocument:
    markdown: str
    metadata: dict


def extract_title_info(raw_title: str) -> dict[str, str]:
    """Accept sh./sz./bare stock codes, including full-width parentheses."""
    match = _STOCK_CODE_RE.search(raw_title)
    return {
        "company_name": _STOCK_CODE_RE.sub("", raw_title).replace("综合分析报告", "").strip(),
        "stock_code": match.group(1) if match else "",
    }


def _prepare_markdown(content: str) -> tuple[str, str]:
    """Remove the duplicate cover title/TOC marker without discarding prose.

    Preserve fenced code verbatim. When an H1 report title is removed, promote
    the remaining headings one level for Eisvogel's section numbering and TOC.
    """
    lines = content.lstrip("\ufeff").splitlines()
    fence = None
    title = ""
    body = []
    for line in lines:
        marker = _FENCE_RE.match(line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[marker.end():].strip():
                fence = None
            body.append((line, True))
            continue
        if fence:
            body.append((line, True))
            continue
        heading = _HEADING_RE.match(line)
        if not title and heading and len(heading.group(1)) == 1:
            title = heading.group(2).rstrip("#").strip()
            continue
        if line.strip().upper() == "[TOC]":
            continue
        body.append((line, False))

    rendered = []
    for line, code in body:
        heading = _HEADING_RE.match(line) if not code else None
        if title and heading and len(heading.group(1)) > 1:
            line = line[1:]
        rendered.append(line)
    return title, "\n".join(rendered).strip("\n") + "\n"


def prepare_report(
    md_content: str,
    company_name: str = "",
    stock_code: str = "",
    analysis_date: str = "",
) -> ReportDocument:
    """Use native Pandoc Markdown for tables, equations, lists and links."""
    title, markdown = _prepare_markdown(md_content)
    info = extract_title_info(title)
    company = company_name or info["company_name"] or "金融分析报告"
    code = stock_code or info["stock_code"]
    for prefix in ("sh.", "sz."):
        code = code.removeprefix(prefix)
    date = analysis_date or datetime.now().strftime("%Y-%m-%d")
    cjk_font = os.getenv("PDF_CJK_FONT") or (
        "Microsoft YaHei" if os.name == "nt" else "FandolHei-Regular.otf"
    )
    latin_options = [
        "BoldFont=texgyreheros-bold.otf",
        "ItalicFont=texgyreheros-italic.otf",
        "BoldItalicFont=texgyreheros-bolditalic.otf",
    ]
    metadata = {
        "title": company,
        "subtitle": f"综合分析报告  /  {code}" if code else "综合分析报告",
        "author": ["FINEX 研究手记"],
        "date": date,
        "titlepage": True,
        "titlepage-color": "FFF8EF",
        "titlepage-text-color": "3F3A36",
        "titlepage-rule-color": "D98267",
        "titlepage-rule-height": 0,
        "toc-title": "阅读目录",
        "toc-own-page": True,
        "colorlinks": True,
        "hyperrefoptions": ["hypertexnames=false"],
        "linkcolor": "FinexClay",
        "urlcolor": "FinexSageDark",
        "header-left": "FINEX  /  研究手记",
        "header-right": code or "综合分析报告",
        "footer-left": company,
        "footer-center": "慢慢读，认真想。",
        "mainfont": "texgyreheros-regular.otf",
        "mainfontoptions": latin_options,
        "sansfont": "texgyreheros-regular.otf",
        "sansfontoptions": latin_options,
        "monofont": "lmmono10-regular.otf",
        "CJKmainfont": cjk_font,
        "CJKsansfont": cjk_font,
        "CJKmonofont": cjk_font,
        "CJKoptions": ["AutoFakeBold=1.8"],
        "fontsize": "11pt",
        "linestretch": 1.28,
        "geometry": ["margin=23mm", "top=26mm", "headheight=18pt", "headsep=8mm"],
        "table-use-row-colors": True,
        "caption-justification": "raggedright",
        "lang": "en-US",
    }
    return ReportDocument(markdown, metadata)
