from pathlib import Path
import re

page = Path('frontend/index.html')
html = page.read_text(encoding='utf-8')
html = html.replace('    <div class="workbench-ambient workbench-ambient-one" aria-hidden="true"></div>\n', '')
html = html.replace('    <div class="workbench-ambient workbench-ambient-two" aria-hidden="true"></div>\n', '')
html = html.replace('FINEX / 小熊研究手记', 'FINEX / 研究工作台')
html = re.sub(r'<span class="agent-monogram" aria-hidden="true">.*?</span>', '', html)
html = re.sub(r'<span class="section-index" aria-hidden="true">.*?</span>', '', html)
html = re.sub(r'\s*<div class="summary-companion" aria-hidden="true">.*?</div>', '', html, flags=re.S)
html = re.sub(r'<span class="agent-discipline">.*?</span>', '', html)
html = html.replace('<span class="agent-number">RESEARCH NOTES</span>', '<span class="agent-number">05</span>')

# Put the section heading above both research columns, and make the market a
# sibling of both columns so it occupies its own full-width bottom row.
intro_start = html.index('          <div class="workspace-intro">')
intro_end = html.index('          <div class="agent-grid', intro_start)
intro = html[intro_start:intro_end]
html = html[:intro_start] + html[intro_end:]
html = html.replace('        <main class="agent-workspace">', intro + '        <main class="agent-workspace">', 1)
market_start = html.index('            <section class="market-overview"')
market_end = html.index('            </section>', market_start) + len('            </section>')
market = html[market_start:market_end]
market = '\n'.join(line[4:] for line in market.splitlines())
html = html[:market_start] + html[market_end:]
summary_start = html.index('        <article class="workbench-agent-card agent-card agent-card-summary"')
summary_end = html.index('        </article>', summary_start) + len('        </article>')
html = html[:summary_end] + '\n\n' + market + html[summary_end:]
html = html.replace('\n\n\n          </div>\n        </main>', '\n          </div>\n        </main>')
html = html.replace('          <div class="market-quote" id="marketQuote">', '          <div class="market-toolbar">\n          <div class="market-quote" id="marketQuote">', 1)
html = html.replace('          <div id="workbenchMarketChart"', '          </div>\n          <div id="workbenchMarketChart"', 1)
page.write_text(html, encoding='utf-8')
