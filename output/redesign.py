from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
html_path = root / 'frontend/index.html'
html = html_path.read_text(encoding='utf-8')
summary_start = html.index('            <article class="workbench-agent-card agent-card agent-card-summary"')
summary_end = html.index('            </article>', summary_start) + len('            </article>')
summary = html[summary_start:summary_end]
html = html[:summary_start] + html[summary_end:]
market_start = html.index('        <aside class="market-overview">')
market_end = html.index('        </aside>', market_start) + len('        </aside>')
market = html[market_start:market_end].replace('<aside class="market-overview">', '<section class="market-overview" aria-labelledby="marketOverviewTitle">').replace('</aside>', '</section>')
market = market.replace('<h2>行情概览</h2>', '<h2 id="marketOverviewTitle">行情概览</h2>')
html = html[:market_start] + summary + html[market_end:]
grid_end = html.index('          </div>\n        </main>', html.index('id="agentGrid"'))
html = html[:grid_end] + market + '\n' + html[grid_end:]
html = html.replace('class="workbench-agent-card agent-card agent-card-summary"', 'class="workbench-agent-card agent-card agent-card-summary" aria-label="综合研判"')
# Decorative charts imply data without presenting research results. Keep the actual market chart.
html = re.sub(r'              <div class="agent-microchart (?:micro-bars|micro-trend|micro-valuation|micro-news)"[^\n]*\n', '', html)
html = re.sub(r'<div class="agent-microchart agent-summary-chart"[^\n]*', '''<div class="summary-companion" aria-hidden="true">
                  <svg viewBox="0 0 240 180" fill="none">
                    <ellipse cx="120" cy="160" rx="65" ry="8" fill="#e7e9e2"/>
                    <path d="M121 62C92 60 87 39 90 28C113 26 128 40 121 62Z" fill="#a7c9aa"/>
                    <path d="M122 63C123 41 141 31 156 34C154 54 142 64 122 63Z" fill="#c4d8b4"/>
                    <path d="M121 77V53" stroke="#67977d" stroke-width="4" stroke-linecap="round"/>
                    <rect x="63" y="65" width="116" height="89" rx="38" fill="#e1eee5" stroke="#b6d2bf" stroke-width="2"/>
                    <circle cx="101" cy="106" r="4" fill="#496e5d"/><circle cx="141" cy="106" r="4" fill="#496e5d"/>
                    <path d="M114 119Q121 126 128 119" stroke="#496e5d" stroke-width="3" stroke-linecap="round"/>
                    <ellipse cx="88" cy="119" rx="9" ry="5" fill="#efc8be"/><ellipse cx="154" cy="119" rx="9" ry="5" fill="#efc8be"/>
                    <path d="M54 76L56 69L58 76L65 78L58 80L56 87L54 80L47 78Z" fill="#c1b5de"/>
                    <path d="M188 111L190 104L192 111L199 113L192 115L190 122L188 115L181 113Z" fill="#e7c58e"/>
                  </svg>
                  <span>多一点依据，少一点猜测</span>
                </div>''', html)
html = html.replace('FINEX RESEARCH · MULTI-AGENT DESK', 'FINEX · 研究小站')
html = html.replace('五位分析师正在协同研究，每项完成后即时呈现阶段摘要。', '让研究有条理，让判断更从容。')
html = html.replace('<span class="agent-monogram">', '<span class="agent-monogram" aria-hidden="true">')
html = html.replace('<div class="agent-card-top"><span class="agent-number">05</span>', '<div class="agent-card-top"><span class="agent-number">✦</span>')
html_path.write_text(html, encoding='utf-8')

css_path = root / 'frontend/workbench.css'
css = css_path.read_text(encoding='utf-8')
report = css[css.index('.workbench-report-shell.report-section'):]
# Carry the new palette through report reading and its existing responsive rules.
for old, new in {
    'rgba(128,97,39,': 'rgba(80,119,99,', 'rgba(96,72,39,': 'rgba(80,119,99,',
    'rgba(91,70,43,': 'rgba(80,119,99,', 'rgba(250,247,240,.72)': '#ffffff',
    '#fffdfa': '#ffffff', '#e9e3d8': '#e7ebe5', '#eee7db': '#e7ebe5',
    '#443e35': '#46544c', '#302a22': '#2e4439', '#625849': '#607268',
    '#9a8c75': '#8b9e93', '#6c5728': '#507763', '#c5b58f': '#b8cfbf',
    '#eae3d7': '#e7ebe5', '#f5f1e9': '#f0f5ef', '#695432': '#507763',
    '#f7f4ee': '#f6f8f3', '#e5ded1': '#e7ebe5', '#eae4d9': '#e7ebe5',
    '#65543c': '#507763', '#f4efe5': '#edf4ee', '#faf8f3': '#f7faf7',
}.items():
    report = report.replace(old, new)
report = report.replace('.market-overview { position: static; }', '.agent-card-summary { position: static; }')
report = report.replace('.workbench-market-chart { height: 430px; }', '.workbench-market-chart { height: 280px; }')
report = report.replace('min-height: 238px;', 'min-height: 172px;')
report = report.replace('.agent-workspace, .market-overview { border-radius: 20px; }', '.market-overview { border-radius: 20px; }')
report = report.replace('.workbench-market-chart { min-height: 340px; height: 340px; }', '.workbench-market-chart { min-height: 240px; height: 240px; }')
report = report.replace('  .workbench-layout { grid-template-columns: 1fr; }', '  .workbench-layout { grid-template-columns: 1fr; }\n  .agent-card-summary { grid-row: 1; }')
css_path.write_text((root / 'output/workbench-theme.css').read_text(encoding='utf-8') + '\n' + report, encoding='utf-8')

js_path = root / 'frontend/workbench.js'
js = js_path.read_text(encoding='utf-8')
for old, new in {
    '#74695b': '#708077', 'rgba(83,64,41,.06)': 'rgba(80,119,99,.06)',
    'rgba(83,64,41,.16)': 'rgba(80,119,99,.14)', '#496f5c': '#64977d',
    '#9b4d43': '#cc8585', '#557a66': '#91b7a1', '#a0473e': '#dfa4a4',
    '#806127': '#8c7bb0', '#687a82': '#6f9aa6',
}.items():
    js = js.replace(old, new)
js_path.write_text(js, encoding='utf-8')
