"""
PDF Converter Module - Async wrapper for PDF generation.

Converts MD report files to professional PDF.
Supports two backends:
  1. xhtml2pdf (default) - Pure Python, no system deps, works on Windows/Linux/macOS
  2. WeasyPrint (optional) - Higher quality, requires GTK/Pango system libraries

Runs PDF generation in a thread executor to avoid blocking the async event loop.
Includes robust exception isolation to never crash the main agent pipeline.
"""

import os
import asyncio
import glob
from typing import Optional

from src.utils.pdf_styles import render_report_html, extract_title_info
from src.utils.logging_config import setup_logger, ERROR_ICON, SUCCESS_ICON, WAIT_ICON

logger = setup_logger(__name__)

# Try to import PDF engines
_HAS_XHTML2PDF = False
_HAS_WEASYPRINT = False

try:
    from xhtml2pdf import pisa
    _HAS_XHTML2PDF = True
except ImportError:
    pass

try:
    from weasyprint import HTML as WeasyHTML
    _HAS_WEASYPRINT = True
except ImportError:
    pass

# Choose engine
if _HAS_WEASYPRINT:
    _PDF_ENGINE = "weasyprint"
    logger.info(f"PDF engine: WeasyPrint (high quality)")
elif _HAS_XHTML2PDF:
    _PDF_ENGINE = "xhtml2pdf"
    logger.info(f"PDF engine: xhtml2pdf (pure Python, cross-platform)")
else:
    _PDF_ENGINE = None
    logger.warning(f"{ERROR_ICON} No PDF engine available. Install xhtml2pdf or weasyprint.")


# ============================================================================
# Chinese Font Registration for xhtml2pdf / ReportLab
# ============================================================================

_CN_FONTS_REGISTERED = False
_CJK_FONT_ALIASES = {}

def _register_chinese_fonts():
    """
    Register Chinese fonts for xhtml2pdf / ReportLab.

    Strategy:
    1. First, register ReportLab's built-in CID fonts (STSong-Light etc.)
       These work everywhere without any external files.
    2. Then, register system TTF/TTC fonts (SimHei, SimSun, Microsoft YaHei etc.)
       These provide better quality but require the font files to exist on disk.
    3. Finally, map CSS font-family names into xhtml2pdf's font table.
    """
    global _CN_FONTS_REGISTERED
    if _CN_FONTS_REGISTERED:
        return

    registered = []

    # --- Step 1: Built-in CID fonts (always available) ---
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        cid_fonts = ["STSong-Light", "MSung-Light", "HeiseiMin-W3", "HeiseiKakuGo-W5"]
        for name in cid_fonts:
            try:
                pdfmetrics.registerFont(UnicodeCIDFont(name))
                registered.append(name)
            except Exception:
                pass
    except ImportError:
        pass

    # --- Step 2: System TTF/TTC fonts ---
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.fonts import addMapping

        search_paths = []
        if os.name == "nt":
            search_paths.append(r"C:\Windows\Fonts")
        else:
            search_paths.extend([
                "/usr/share/fonts",
                "/usr/local/share/fonts",
                os.path.expanduser("~/.fonts"),
                "/System/Library/Fonts",
                "/Library/Fonts",
            ])

        font_targets = [
            ("simhei.ttf",  "SimHei"),
            ("simsun.ttc",  "SimSun"),
            ("msyh.ttc",    "MicrosoftYaHei"),
            ("notosanssc*", "NotoSansSC"),
        ]

        for font_dir in search_paths:
            if not os.path.exists(font_dir):
                continue
            all_files = os.listdir(font_dir)

            for pattern, name in font_targets:
                if pattern.endswith("*"):
                    matches = glob.glob(os.path.join(font_dir, pattern))
                    if not matches:
                        continue
                    font_path = matches[0]
                else:
                    font_path = os.path.join(font_dir, pattern)
                    if pattern.lower() not in [f.lower() for f in all_files]:
                        continue

                try:
                    pdfmetrics.registerFont(TTFont(name, font_path))
                    registered.append(name)
                except Exception:
                    pass
    except ImportError:
        pass

    # --- Step 3: Map fonts into xhtml2pdf's internal table ---
    # xhtml2pdf resolves CSS font-family through pisaContext.fontList.
    # We need to make our font names known to it by monkey-patching the default
    # font list that gets initialized for every new pisaContext.
    try:
        import xhtml2pdf.default as xhtml2pdf_default

        # The DEFAULT_CSS in xhtml2pdf already defines font-family.
        # We override getFontName behavior so it finds our CJK fonts.
        _map_cjk_fonts_in_xhtml2pdf(registered)
    except Exception:
        pass

    _CN_FONTS_REGISTERED = True
    logger.info(f"Registered Chinese fonts: {registered}")


def _map_cjk_fonts_in_xhtml2pdf(registered_fonts):
    """
    Monkey-patch xhtml2pdf's font resolution so CSS font-family: "SimSun"
    etc. actually resolves to the registered ReportLab fonts.
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.lib.fonts import addMapping

    # Build a mapping: CSS name -> ReportLab registered name
    # Priority: TTF fonts > CID fonts
    font_aliases = {}
    for name in registered_fonts:
        font_aliases[name] = name
        font_aliases[name.lower()] = name

    # Also add common CSS names that map to our fonts
    font_aliases.update({
        "simsun":       "SimSun" if "SimSun" in registered_fonts else "STSong-Light",
        "simhei":       "SimHei" if "SimHei" in registered_fonts else "HeiseiKakuGo-W5",
        "songti":       "STSong-Light",
        "heiti":        "SimHei" if "SimHei" in registered_fonts else "HeiseiKakuGo-W5",
        "yahei":        "MicrosoftYaHei" if "MicrosoftYaHei" in registered_fonts else "SimHei" if "SimHei" in registered_fonts else "STSong-Light",
    })

    # Store globally so _inject_fonts_to_xhtml2pdf can use it
    global _CJK_FONT_ALIASES
    _CJK_FONT_ALIASES = font_aliases


# Register fonts at import time
if _PDF_ENGINE == "xhtml2pdf":
    _register_chinese_fonts()


def _render_with_xhtml2pdf(html_content: str, pdf_path: str) -> bool:
    """Render HTML to PDF using xhtml2pdf (pure Python, cross-platform)."""
    # Pre-load Chinese fonts into xhtml2pdf's context before parsing HTML.
    # We do this via ReportLab registration + xhtml2pdf's internal font table,
    # because @font-face CSS parsing is broken on Windows (temp file permission issue).
    _inject_fonts_to_xhtml2pdf()

    with open(pdf_path, "wb") as pdf_file:
        result = pisa.CreatePDF(
            html_content,
            dest=pdf_file,
            encoding="utf-8",
            path=os.path.dirname(pdf_path)
        )
    return not result.err


def _inject_fonts_to_xhtml2pdf():
    """
    Monkey-patch xhtml2pdf's pisaContext.getFontName so that when the CSS
    requests a CJK font-family, it resolves to our registered ReportLab fonts.

    xhtml2pdf resolves CSS font-family -> ReportLab font via pisaContext.fontList.
    We patch getFontName to check our CJK aliases before falling back to default.
    """
    try:
        from xhtml2pdf import context as ctx

        if hasattr(ctx, '_CJK_PATCHED'):
            return

        original_getFontName = ctx.pisaContext.getFontName

        def patched_getFontName(self, names, default=""):
            """Patched version that resolves CJK font names."""
            if isinstance(names, str):
                names_list = [n.strip().strip('"\'') for n in names.split(",")]
            elif isinstance(names, list):
                names_list = [str(n).strip().strip('"\'') for n in names]
            else:
                names_list = [str(names)]

            for name in names_list:
                lookup = name.lower()
                if lookup in _CJK_FONT_ALIASES:
                    resolved = _CJK_FONT_ALIASES[lookup]
                    # Also add to fontList so future lookups are fast
                    self.fontList[lookup] = resolved
                    self.fontList[name] = resolved
                    return resolved

            return original_getFontName(self, names, default)

        ctx.pisaContext.getFontName = patched_getFontName
        ctx._CJK_PATCHED = True
        logger.info(f"CJK font patch applied to xhtml2pdf (aliases: {len(_CJK_FONT_ALIASES)})")

    except Exception as e:
        logger.warning(f"Could not patch xhtml2pdf font resolution: {e}")


def _render_with_weasyprint(html_content: str, pdf_path: str, temp_dir: str) -> bool:
    """Render HTML to PDF using WeasyPrint (higher quality, needs system deps)."""
    import tempfile
    temp_html = os.path.join(temp_dir, "_weasy_temp.html")
    try:
        with open(temp_html, "w", encoding="utf-8") as f:
            f.write(html_content)
        html_doc = WeasyHTML(filename=temp_html)
        html_doc.write_pdf(pdf_path)
        return True
    finally:
        if os.path.exists(temp_html):
            os.remove(temp_html)


def derive_pdf_path(md_path: str) -> str:
    """根据 MD 报告路径推导对应的 PDF 路径。

    约定：reports/md/xxx.md -> reports/pdf/xxx.pdf
    若 MD 不在名为 "md" 的目录下，则 PDF 与 MD 同目录、同名换 .pdf 后缀。

    Args:
        md_path: Absolute path to the .md report file.

    Returns:
        Absolute path to the corresponding .pdf file (not guaranteed to exist).
    """
    md_path = str(md_path)
    md_dir = os.path.dirname(md_path)
    md_base = os.path.splitext(os.path.basename(md_path))[0]
    if os.path.basename(md_dir) == "md":
        return os.path.join(os.path.dirname(md_dir), "pdf", md_base + ".pdf")
    return os.path.splitext(md_path)[0] + ".pdf"


def convert_md_to_pdf(md_path: str, company_name: str = "",
                      stock_code: str = "", analysis_date: str = "") -> Optional[str]:
    """
    Convert a Markdown report file to a professionally styled PDF.

    This is a synchronous, CPU-intensive function. Callers should invoke it
    via run_in_executor to avoid blocking the event loop.

    Exception isolation: all PDF engine errors are caught and logged.
    Returns None on failure instead of raising.

    Args:
        md_path: Absolute path to the .md report file
        company_name: Company name for the cover page
        stock_code: Stock code for the cover page
        analysis_date: Date string for the cover page

    Returns:
        Absolute path to the generated .pdf file, or None on failure.
    """
    try:
        if not _PDF_ENGINE:
            logger.error(f"{ERROR_ICON} No PDF engine available")
            return None

        md_path = str(md_path)
        if not os.path.exists(md_path):
            logger.error(f"{ERROR_ICON} MD file not found: {md_path}")
            return None

        # Derive PDF path: reports/md/xxx.md -> reports/pdf/xxx.pdf
        # (shared logic; ensures directory convention changes only need one edit)
        pdf_path = derive_pdf_path(md_path)
        # Ensure the PDF output directory exists (only creates reports/pdf/ when
        # the MD lives under a "md" dir; otherwise the MD dir already exists).
        if os.path.basename(os.path.dirname(md_path)) == "md":
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

        logger.info(f"{WAIT_ICON} Starting PDF generation ({_PDF_ENGINE}): {os.path.basename(md_path)}")

        # Read MD content
        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        if not md_content.strip():
            logger.error(f"{ERROR_ICON} MD file is empty: {md_path}")
            return None

        # Extract company_name/stock_code from MD content if not provided
        import re
        if not company_name or not stock_code:
            h1_match = re.search(r'^#\s+(.+?)(?:\s*综合分析报告)?$', md_content, re.MULTILINE)
            if h1_match:
                title = h1_match.group(1).strip()
                # Use the shared parser so the extraction logic stays in sync
                # with parse_md_to_sections (handles sh./sz./bare code formats).
                info = extract_title_info(title)
                if not stock_code:
                    stock_code = info["stock_code"]
                if not company_name:
                    company_name = info["company_name"]

        # Build styled HTML via Jinja2 template
        html_content = render_report_html(
            md_content=md_content,
            company_name=company_name,
            stock_code=stock_code,
            analysis_date=analysis_date,
        )

        # Render PDF using the selected engine
        temp_dir = os.path.dirname(md_path)
        success = False

        if _PDF_ENGINE == "weasyprint":
            success = _render_with_weasyprint(html_content, pdf_path, temp_dir)
        elif _PDF_ENGINE == "xhtml2pdf":
            success = _render_with_xhtml2pdf(html_content, pdf_path)

        if not success:
            logger.error(f"{ERROR_ICON} PDF engine returned error for {md_path}")
            return None

        # Verify PDF was created
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            file_size_kb = os.path.getsize(pdf_path) / 1024
            logger.info(
                f"{SUCCESS_ICON} PDF generated successfully: {os.path.basename(pdf_path)} ({file_size_kb:.1f} KB)")
            return pdf_path
        else:
            logger.error(f"{ERROR_ICON} PDF file was not created or is empty: {pdf_path}")
            return None

    except Exception as e:
        logger.error(f"{ERROR_ICON} PDF generation failed for {md_path}: {e}", exc_info=True)
        return None


async def generate_pdf_background(md_path: str, state_data: dict,
                                   company_name: str = "",
                                   stock_code: str = "",
                                   analysis_date: str = "") -> None:
    """
    Async wrapper that runs PDF generation in a thread executor.

    This function is designed to be called via asyncio.create_task() as a
    fire-and-forget background job. It updates state_data['pdf_path'] on success
    and sets it to None on failure.

    Args:
        md_path: Path to the .md report file
        state_data: Mutable dict from the agent state (data field)
        company_name: Company name for the cover page
        stock_code: Stock code for the cover page
        analysis_date: Date string for the cover page
    """
    loop = asyncio.get_event_loop()
    try:
        pdf_path = await loop.run_in_executor(
            None,
            convert_md_to_pdf,
            md_path,
            company_name,
            stock_code,
            analysis_date
        )
        if pdf_path:
            state_data["pdf_path"] = pdf_path
            logger.info(f"{SUCCESS_ICON} Background PDF generation completed: {pdf_path}")
        else:
            state_data["pdf_path"] = None
            logger.warning(f"Background PDF generation returned None for {md_path}")

    except Exception as e:
        logger.error(f"{ERROR_ICON} Unexpected error in generate_pdf_background: {e}", exc_info=True)
        state_data["pdf_path"] = None
