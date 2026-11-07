"""Conservative reader-facing names and labels; never rewrite research claims."""

import re


REPORT_STYLE_GUIDANCE = """
读者表达要求：
- 使用中文指标名称，必要时保留ROE、PE、MACD等常用缩写；不要把roeAvg、CFOToOR、peTTM等接口字段名直接写进报告。
  保留TTM、最近季末、单季度/累计等口径，现金流/收入等比率写清分子分母。
- 标签直接说明主题，不使用“观察项”等通用前缀；不要在“投资建议”章节下再写同名标签，可用“配置思路”。
- 每节直接写事实及意义，不用“近期市场舆情产生多维度驱动”“展现高度逻辑共振”等可套用于任何公司的开场。
  没有证据支持的“极强、顶尖、完美”等修饰不要使用，正面或负面判断给出对应事实。
- 同一节的列表和指标表二选一，避免逐字重复同一组数字；表格适合对比，段落用于解释原因和限制。
- 不复述写作指令或自我保证，例如“不得将生成日当成行情日”“已做区分”“未提供数据已明确标注缺失”。
  数据限制应说明实际缺少的资料及影响，拿不到时直接说未知，保留缺失和不确定性。
""".strip()

# Only known source field identifiers are translated. Periods and ratio
# denominators remain explicit; values and analytical judgments are untouched.
_FIELDS = {
    "roeAvg": ("加权平均净资产收益率", ("加权平均净资产收益率", "加权净资产收益率", "净资产收益率", "加权ROE", "ROE")),
    "gpMargin": ("毛利率", ("毛利率",)),
    "npMargin": ("净利率", ("净利润率", "净利率")),
    "CFOToOR": ("经营现金流/营业收入", ("经营现金流对营业收入比率", "经营现金流占比", "经营现金流/营业收入")),
    "CFOToNP": ("经营现金流/净利润", ("经营现金流与净利润比值", "经营现金流/净利润")),
    "NRTurnRatio": ("应收账款周转率", ("应收账款周转率",)),
    "INVTurnRatio": ("存货周转率", ("存货周转率",)),
    "peTTM": ("市盈率（TTM）", ("动态市盈率", "市盈率")),
    "pbMRQ": ("市净率（最近季末）", ("市净率",)),
    "psTTM": ("市销率（TTM）", ("市销率",)),
    "epsTTM": ("每股收益（TTM）", ("基本每股收益", "每股收益")),
}
_SUBSTITUTIONS = []
for _key, (_display, _names) in _FIELDS.items():
    _name = "(?:" + "|".join(map(re.escape, _names)) + ")"
    _name = r"(?:\*\*" + _name + r"\*\*|" + _name + ")"
    _code = r"(?:\*\*" + _key + r"\*\*|" + _key + r"(?![A-Za-z0-9_]))"
    _paired = _name + r"(?:[ \t]*[（(][ \t]*" + _code + r"[ \t]*[)）]|[ \t]*" + _code + ")"
    _SUBSTITUTIONS.append((re.compile(_paired), re.compile(r"(?<![A-Za-z0-9_])" + _key + r"(?![A-Za-z0-9_])"), _display))

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LITERALS = re.compile(
    r"(?P<ticks>`+)[^`\n]*?(?P=ticks)"
    r"|!?\[[^\]\n]*\]\((?:\\.|[^\\()\n]|\((?:\\.|[^\\()\n])*\))*\)"
    r"|!?\[[^\]\n]*\](?:\[[^\]\n]*\])?"
    r"|(?:https?://|www\.)[^\s]+"
    r"|\$[^$\n]+\$|\\\([^\n]*?\\\)|\\\[[^\n]*?\\\]"
    r"|<[^>\n]+>"
)


def _readable_fields(text: str) -> str:
    for paired, bare, display in _SUBSTITUTIONS:
        text = paired.sub(lambda _: display, text)
        text = bare.sub(lambda _: display, text)
    return text


def _polish_line(line: str, section: str) -> str:
    # Remove wrappers without inferring a subject for a formerly generic row.
    line = re.sub(r"^([ \t]*[-*][ \t]+)\*\*观察项[：:][ \t]*\*\*[ \t]*", r"\1", line)
    line = re.sub(r"^([ \t]*[-*][ \t]+)\*\*观察项[：:][ \t]*", r"\1**", line)
    if section == "投资建议":
        line = re.sub(r"^([-*][ \t]+\*\*)投资建议(?=[：:]?\*\*)", r"\1配置思路", line)
    pieces, cursor = [], 0
    for literal in _LITERALS.finditer(line):
        pieces.extend((_readable_fields(line[cursor:literal.start()]), literal.group()))
        cursor = literal.end()
    pieces.append(_readable_fields(line[cursor:]))
    return "".join(pieces)


def polish_report_markdown(markdown: str) -> str:
    """Keep literal code/math/links intact; do not deduplicate research facts."""
    result, fence, math_end, section = [], None, None, ""
    for line in markdown.splitlines(keepends=True):
        marker = _FENCE.match(line)
        if fence:
            result.append(line)
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not line[marker.end():].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            result.append(line)
            continue
        if math_end:
            result.append(line)
            if math_end in line:
                math_end = None
            continue
        stripped = line.strip()
        if stripped.startswith(("$$", r"\[")):
            opening, closing = ("$$", "$$") if stripped.startswith("$$") else (r"\[", r"\]")
            if closing not in stripped[len(opening):]:
                math_end = closing
            result.append(line)
            continue
        if re.match(r"^(?: {4}|\t| {0,3}\[[^\]]+\]:)", line):
            result.append(line)
            continue
        heading = re.match(r"^#{1,2}[ \t]+(.+?)[ \t]*#*[ \t]*$", line.rstrip("\r\n"))
        if heading:
            section = heading[1]
        result.append(_polish_line(line, section))
    return "".join(result)
