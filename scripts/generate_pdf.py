"""Generate a FINEX PDF from an existing Markdown file without calling a model."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", type=Path, help="Existing Markdown report")
    parser.add_argument("--company", default="", help="Override cover company name")
    parser.add_argument("--code", default="", help="Override cover stock code")
    parser.add_argument("--date", default="", help="Analysis date, e.g. 2026-10-31")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / "agents" / ".env", override=False)
    from src.utils.pdf_converter import convert_md_to_pdf, get_pdf_status

    result = convert_md_to_pdf(str(args.markdown.resolve()), args.company, args.code, args.date)
    if not result:
        print(get_pdf_status(str(args.markdown.resolve()))["message"], file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
