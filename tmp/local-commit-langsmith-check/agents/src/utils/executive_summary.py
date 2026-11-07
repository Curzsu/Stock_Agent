"""Content contract for the independently readable, single-page report summary."""

import re


EXECUTIVE_SUMMARY_GUIDANCE = """
摘要是可脱离封面、正文独立阅读的研究速览，必须作为报告第一个二级章节，标题严格使用“## 摘要”。
所有章节标题必须顶格且前后留空行，不把标题缩进到列表或正文段落中。
公司、代码和分析日期由应用补充，不要在摘要里另造身份行。不要写“详见正文”“如上所述”。
先写一段 Markdown 引用（>），约60–100字：说明公司业务/核心看点、当前最重要的矛盾、
总体判断及适用期限；区分企业经营质量与当前价格是否有吸引力，不强行给评级或收益率。
接着写六个单层列表要点，每项1–2句、约60–100字，围绕重要事实及其对判断的影响：
- 经营与财务：盈利与增长的驱动、现金流/财务质量，按行业挑重点，不堆指标。
- 估值与预期：当前价格对应什么估值，和已取得的同口径历史/同行相比如何；
  只有材料支持时才判断市场已反映多少预期，没有比较或测算就明确不能确认，不推演目标价。
- 走势与时机：短期趋势、量价和最重要的价格位置（有依据才写），与中长期经营判断分开。
- 催化与分歧：已核实的重要事件如何影响经营或定价，解释支持和反对观点的主要分歧；
  区分已发生事实与待验证预期，不能把新闻热度直接当成业绩或股价上涨证据。
- 风险与反证：最可能破坏核心判断的1–2个具体风险，以及什么变化会让当前判断不再成立。
  反证须对应经营或估值的核心依据；跌破均线等技术信号只影响短期走势，不能据此认定长期经营、分红逻辑失效。
  成文时给出公司具体的经营或估值反证，不复述这条短期与长期的写作区分要求。
- 后续观察：接下来最值得跟踪的1–2项事实/指标及其意义，不编造日期、阈值或事件。
要点标签可随内容自然表达，但六个方面都应得到交代；没有相应数据的方面明确标注缺失及影响，
不要为了凑齐内容补造事实，不要求读者懂所有指标，简洁解释指标变化为什么影响判断即可。
最后独立一行“**数据边界：** …”，注明材料给出的行情日、财务报告期、重要缺失/冲突及对结论的限制；
未知日期或报告期写未提供，不能将报告生成日当成行情日，单季度、累计和TTM不得混用。
数据边界只写实际的数据日期、口径与限制，不复述写作指令，不写“不得将…”或“已做区分”等自我保证。
摘要目标650–850个非空白字符，硬上限1000；最多12个非空行，以一段结论、六个要点和一行边界为主。
各要点之间可以空行，不在要点内换行。不要使用表格、图片、代码、公式、脚注、子标题或多级列表。
摘要可以复述正文的必要关键数据，但不要把四份分析机械拼接，也不要逐一罗列所有指标。
""".strip()

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _summary_bounds(report: str) -> tuple[int, int]:
    """Locate a real H2 section, ignoring headings inside fenced examples."""
    sections = []
    offset, fence, previous_blank = 0, None, True
    for line in report.splitlines(keepends=True):
        marker = _FENCE.match(line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[marker.end():].strip():
                fence = None
        elif fence is None:
            heading = _HEADING.match(line.rstrip("\r\n"))
            # Match prepare_report's column-zero headings and Pandoc's default
            # blank_before_header rule. A list/example must not bypass paging.
            if heading and previous_blank and len(heading.group(1)) <= 2:
                sections.append((offset, offset + len(line), len(heading.group(1)), heading.group(2)))
        offset += len(line)
        previous_blank = not line.strip()
    summaries = [i for i, section in enumerate(sections) if section[2] == 2 and section[3] in ("摘要", "一页摘要")]
    if len(summaries) != 1:
        raise ValueError("报告必须包含且仅包含一个“## 摘要”章节")
    index = summaries[0]
    if any(section[2] == 2 for section in sections[:index]):
        raise ValueError("摘要必须是报告第一个二级章节")
    if index + 1 == len(sections) or not report[sections[index + 1][1]:].strip():
        raise ValueError("摘要后缺少完整报告正文")
    return sections[index][1], sections[index + 1][0]


def validate_executive_summary(report: str) -> None:
    """Reject unbounded layout instead of silently cutting evidence or risks."""
    start, end = _summary_bounds(report)
    summary = report[start:end].strip()
    lines = [line for line in summary.splitlines() if line.strip()]
    if len(re.sub(r"\s", "", summary)) > 1000 or len(lines) > 12:
        raise ValueError("摘要超出1000个非空白字符或12个非空行，请精简重写，不要截断")
    unsupported = re.compile(
        r"(?m)^(?: {0,3}(?:#{1,6}\s|`{3,}|~{3,}|\||:::|<|\$\$)| {2,}[-*+]\s| {4}\S)"
        r"|!\[|\[\^|`|\$|\\\(|\\\["
    )
    if unsupported.search(summary):
        raise ValueError("摘要只使用短段落、引用和单层列表，不使用表格、图片、代码或公式")
    bullets = re.findall(r"(?m)^[-*][ \t]+\S", summary)
    if not re.search(r"(?m)^>[ \t]*\S", summary) or not 5 <= len(bullets) <= 7:
        raise ValueError("摘要需有一段引用结论和5至7个单层要点，兼顾各方面")
    if not re.search(r"(?m)^\*\*数据边界[：:]\*\*", summary):
        raise ValueError("摘要缺少独立的“**数据边界：**”说明")


def _literal(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", " ".join(value.split()))


def add_summary_identity(
    report: str, company_name: str, stock_code: str, analysis_date: str,
    missing_dimensions: tuple[str, ...] = (),
) -> str:
    """Attach application-owned identity so the page can stand on its own."""
    start, _ = _summary_bounds(report)
    code = stock_code.removeprefix("sh.").removeprefix("sz.")
    identity = (
        f"**研究对象：** {_literal(company_name or '公司未提供')}（{_literal(code or '代码未提供')}）"
        f" · **分析日期：** {_literal(analysis_date or '日期未提供')}"
    )
    if missing_dimensions:
        identity += "\n\n**资料缺口：** " + "、".join(_literal(name) for name in missing_dimensions) + "未取得有效分析，相关判断待验证。"
    return report[:start].rstrip() + "\n\n" + identity + "\n\n" + report[start:].lstrip()
