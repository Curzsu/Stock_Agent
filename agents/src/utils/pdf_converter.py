"""Generate Eisvogel PDFs off the event loop and publish complete files atomically."""

import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree

from src.utils.pdf_styles import prepare_report
from src.utils.logging_config import setup_logger

logger = setup_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_DIR = Path(__file__).with_name("pdf_templates")
PORTABLE_TOOLS = PROJECT_ROOT / ".tools" / "pdf"


def derive_pdf_path(md_path: str) -> str:
    """reports/md/name.md -> reports/pdf/name.pdf, otherwise beside the source."""
    md_path = str(md_path)
    directory = os.path.dirname(md_path)
    stem = os.path.splitext(os.path.basename(md_path))[0]
    if os.path.basename(directory) == "md":
        return os.path.join(os.path.dirname(directory), "pdf", stem + ".pdf")
    return os.path.splitext(md_path)[0] + ".pdf"


def _find_tool(override: str, name: str) -> Optional[str]:
    if override:
        found = shutil.which(override)
        if found:
            return found
        candidate = Path(override).expanduser()
        return str(candidate.resolve()) if candidate.is_file() else None
    suffix = ".exe" if os.name == "nt" else ""
    portable = PORTABLE_TOOLS / name / (name + suffix)
    return str(portable) if portable.is_file() else shutil.which(name)


def _resolve_toolchain() -> tuple[str, str]:
    pandoc = _find_tool(os.getenv("PANDOC_PATH", ""), "pandoc")
    if not pandoc:
        raise RuntimeError("缺少 Pandoc 3；Windows 请运行 scripts/setup_pdf.ps1，其他平台请安装 Pandoc。")
    version = subprocess.run(
        [pandoc, "--version"], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=10, check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    match = re.search(r"pandoc(?:\.exe)?\s+(\d+)\.", version.stdout)
    if not match or int(match.group(1)) < 3:
        raise RuntimeError("Eisvogel 需要 Pandoc 3；请升级或运行 scripts/setup_pdf.ps1。")
    configured = os.getenv("PDF_LATEX_ENGINE", "")
    if configured:
        name = Path(configured).stem.lower()
        if name not in {"xelatex", "tectonic"}:
            raise RuntimeError("PDF_LATEX_ENGINE 仅支持 xelatex、tectonic 或其完整路径。")
        engine = _find_tool(configured, name)
    else:
        engine = _find_tool("", "xelatex") or _find_tool("", "tectonic")
    if not engine:
        raise RuntimeError("缺少 XeLaTeX/Tectonic；Windows 请运行 scripts/setup_pdf.ps1。")
    return pandoc, engine


def _run_pandoc(command: list[str], *, cwd: str, timeout: float) -> None:
    """Bound the entire build, including the LaTeX child process on timeout."""
    environment = os.environ.copy()
    if os.name == "nt" and not environment.get("FONTCONFIG_FILE"):
        # Portable Tectonic has no system fonts.conf on Windows. Give fontconfig
        # explicit font/cache directories without changing process-wide settings.
        config = ElementTree.Element("fontconfig")
        font_dirs = [Path(environment.get("WINDIR", r"C:\Windows")) / "Fonts"]
        if environment.get("LOCALAPPDATA"):
            font_dirs.append(Path(environment["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts")
        for directory in font_dirs:
            if directory.is_dir():
                ElementTree.SubElement(config, "dir").text = directory.as_posix()
        cache = PORTABLE_TOOLS / "fontconfig-cache"
        cache.mkdir(parents=True, exist_ok=True)
        ElementTree.SubElement(config, "cachedir").text = cache.as_posix()
        config_path = Path(cwd) / "fonts.conf"
        ElementTree.ElementTree(config).write(config_path, encoding="utf-8", xml_declaration=True)
        environment["FONTCONFIG_FILE"] = str(config_path)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    process = subprocess.Popen(
        command, cwd=cwd, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", **options,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=10, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            process.kill()
        process.communicate(timeout=10)
        raise
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
    if stderr.strip():
        logger.info("Pandoc build notes: %s", stderr[-4000:])


def _write_pdf_status(pdf_path: Path, status: str, message: str = "", timeout: float = 300) -> None:
    """Sidecar survives detached background state and distinguishes failure from waiting."""
    target = pdf_path.with_suffix(".pdf.status.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"status": status, "message": message, "updated_at": time.time(), "timeout": timeout}, stream, ensure_ascii=False)
        temporary.replace(target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def get_pdf_status(md_path: str) -> dict:
    """Read readiness without importing a PDF engine or exposing a partial file."""
    pdf_path = Path(derive_pdf_path(md_path))
    if pdf_path.is_file() and pdf_path.stat().st_size > 0:
        return {"status": "ready", "message": "PDF 已生成"}
    try:
        status = json.loads(pdf_path.with_suffix(".pdf.status.json").read_text(encoding="utf-8"))
        if status["status"] == "pending" and time.time() - status["updated_at"] > status["timeout"] + 30:
            return {"status": "failed", "message": "PDF 生成超时或服务已中断，请重新生成。"}
        return {"status": status["status"], "message": status.get("message", "")}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "pending", "message": "PDF is still being generated"}


def _pandoc_failure_message(error: subprocess.CalledProcessError, pdf_path: Path) -> str:
    """Pandoc may put the TeX error in stdout and download notes in stderr."""
    diagnostics = "\n".join(part for part in (error.stdout, error.stderr) if part) or str(error)
    try:
        pdf_path.with_suffix(".pdf.log").write_text(diagnostics, encoding="utf-8")
    except OSError:
        logger.warning("Could not save PDF build diagnostics: %s", pdf_path)
    lines = diagnostics.splitlines()
    selected = set()
    for index, line in enumerate(lines):
        if re.search(r"error|^!|fatal", line, re.IGNORECASE):
            selected.update(range(index, min(index + 4, len(lines))))
    summary = "\n".join(lines[index] for index in sorted(selected))
    if not summary:
        summary = "\n".join(line for line in lines if not line.startswith("note: downloading"))
    return f"PDF 排版失败：{(summary or diagnostics)[-2500:]}"


def convert_md_to_pdf(
    md_path: str, company_name: str = "", stock_code: str = "", analysis_date: str = "",
) -> Optional[str]:
    """Render native Markdown with the vendored Eisvogel template; isolate failures."""
    pdf_path = Path(derive_pdf_path(str(md_path))).resolve()
    try:
        source = Path(md_path).resolve()
        content = source.read_text(encoding="utf-8")
        if not content.strip():
            raise ValueError("Markdown 报告为空。")
        timeout = float(os.getenv("PDF_TIMEOUT_SECONDS", "300"))
        if not 0 < timeout <= 3600:
            raise ValueError("PDF_TIMEOUT_SECONDS 必须在 0 到 3600 秒之间。")
        _write_pdf_status(pdf_path, "pending", timeout=timeout)
        pandoc, engine = _resolve_toolchain()
        template = TEMPLATE_DIR / "eisvogel.latex"
        theme = TEMPLATE_DIR / "finex-warm.tex"
        cover_art = TEMPLATE_DIR / "assets" / "finex-crayon-cover.png"
        if not template.is_file() or not theme.is_file():
            raise RuntimeError("PDF 模板缺失，请恢复 agents/src/utils/pdf_templates。")
        if not cover_art.is_file():
            raise RuntimeError("封面插画缺失，请恢复 pdf_templates/assets/finex-crayon-cover.png。")
        layout_filter = TEMPLATE_DIR / "report-layout.lua"
        if not layout_filter.is_file():
            raise RuntimeError("正文排版规则缺失，请恢复 pdf_templates/report-layout.lua。")
        report = prepare_report(content, company_name, stock_code, analysis_date)
        logger.info("Generating Eisvogel PDF: %s", source.name)
        with tempfile.TemporaryDirectory(prefix="finex-pdf-", dir=pdf_path.parent) as temporary:
            build_dir = Path(temporary)
            markdown = build_dir / "report.md"
            metadata = build_dir / "metadata.json"
            output = build_dir / "report.pdf"
            markdown.write_text(report.markdown, encoding="utf-8")
            metadata.write_text(json.dumps(report.metadata, ensure_ascii=False), encoding="utf-8")
            command = [
                pandoc, "--from=markdown+lists_without_preceding_blankline-raw_tex-raw_html-yaml_metadata_block",
                "--standalone", "--template", str(template),
                "--include-in-header", str(theme), "--metadata-file", str(metadata),
                "--lua-filter", str(layout_filter),
                # A template variable keeps the path literal (no Markdown escaping
                # of underscores/spaces), regardless of the report's directory.
                "--variable", f"titlepage-background={cover_art.resolve().as_posix()}",
                f"--pdf-engine={engine}", "--table-of-contents", "--toc-depth=2",
                "--number-sections",
                "--resource-path", str(source.parent), "--output", str(output),
            ]
            if Path(engine).stem.lower() == "xelatex":
                command.append("--pdf-engine-opt=-no-shell-escape")
            command.append(str(markdown))
            _run_pandoc(command, cwd=str(build_dir), timeout=timeout)
            if not output.is_file():
                raise RuntimeError("Pandoc 未生成 PDF 文件。")
            with output.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise RuntimeError("Pandoc 输出不是有效的 PDF 文件。")
                stream.seek(max(0, output.stat().st_size - 1024))
                if not stream.read().rstrip().endswith(b"%%EOF"):
                    raise RuntimeError("Pandoc 输出的 PDF 不完整。")
            output.replace(pdf_path)
        _write_pdf_status(pdf_path, "ready")
        try:
            pdf_path.with_suffix(".pdf.log").unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove outdated PDF failure log: %s", pdf_path)
        logger.info("PDF generated: %s (%.1f KB)", pdf_path.name, pdf_path.stat().st_size / 1024)
        return str(pdf_path)
    except Exception as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            message = "PDF 排版超时，请检查字体/LaTeX 依赖或调整 PDF_TIMEOUT_SECONDS。"
        elif isinstance(exc, subprocess.CalledProcessError):
            message = _pandoc_failure_message(exc, pdf_path)
        else:
            message = f"PDF 生成失败：{exc}"
        logger.error("%s (%s)", message, md_path)
        try:
            _write_pdf_status(pdf_path, "failed", message)
        except OSError:
            logger.exception("Could not record PDF failure status")
        return None


async def generate_pdf_background(
    md_path: str, state_data: dict, company_name: str = "", stock_code: str = "", analysis_date: str = "",
) -> None:
    """Keep the report workflow responsive; PDF errors never fail the analysis."""
    try:
        state_data["pdf_path"] = await asyncio.get_running_loop().run_in_executor(
            None, convert_md_to_pdf, md_path, company_name, stock_code, analysis_date,
        )
    except Exception:
        logger.exception("Unexpected background PDF error: %s", md_path)
        state_data["pdf_path"] = None
