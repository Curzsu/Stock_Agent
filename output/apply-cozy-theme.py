from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
page = root / 'frontend/index.html'
html = page.read_text(encoding='utf-8')
icons = {'基': 'bear-face', '技': 'chart', '估': 'coin', '闻': 'letter', '综': 'notebook'}
for label, symbol in icons.items():
    html = html.replace(
        f'<span class="agent-monogram" aria-hidden="true">{label}</span>',
        f'<span class="agent-monogram" aria-hidden="true"><svg viewBox="0 0 64 64"><use href="/static/assets/cozy-doodles.svg#{symbol}"/></svg></span>',
    )
html = re.sub(
    r'<span class="section-index">0[12]</span>',
    '<span class="section-index" aria-hidden="true"><svg viewBox="0 0 40 40"><use href="/static/assets/cozy-doodles.svg#flower"/></svg></span>',
    html,
)
html = html.replace('FINEX · 研究小站', 'FINEX / 小熊研究手记')
html = html.replace('让研究有条理，让判断更从容。', '把复杂的线索，慢慢理清楚。')
html = html.replace('<span class="agent-number">✦</span>', '<span class="agent-number">RESEARCH NOTES</span>')
html = re.sub(
    r'<div class="summary-companion" aria-hidden="true">.*?</div>',
    '''<div class="summary-companion" aria-hidden="true">
              <svg viewBox="0 0 320 250"><use href="/static/assets/cozy-doodles.svg#research-bear"/></svg>
              <span>认真翻翻，慢慢想想。</span>
            </div>''',
    html,
    count=1,
    flags=re.S,
)
# Preload the local font so UI lettering is consistent without an external font CDN.
html = html.replace(
    '  <link rel="stylesheet" href="/static/workbench.css">',
    '  <link rel="preload" href="/static/assets/fonts/ZCOOLKuaiLe-Regular.woff" as="font" type="font/woff" crossorigin>\n  <link rel="stylesheet" href="/static/workbench.css">',
)
page.write_text(html, encoding='utf-8')

sheet = root / 'frontend/workbench.css'
current_css = sheet.read_text(encoding='utf-8')
report = current_css[current_css.index('.workbench-report-shell.report-section'):current_css.index('@media (max-width: 1120px)')]
for old, new in {
    'rgba(80,119,99,': 'rgba(164,124,65,', '#ffffff': '#fffcf6',
    '#607268': '#987b58', '#8b9e93': '#c4a57b', '#e7ebe5': '#ecdfca',
    '#46544c': '#80664d', '#2e4439': '#745337', '#f0f5ef': '#f6ecd8',
    '#364d40': '#8a6d42', '#507763': '#ad8447', '#b8cfbf': '#dcc49a',
    '#f6f8f3': '#fbf5e9', '#edf4ee': '#f4e9d3', '#f7faf7': '#fcf8ed',
    '#8c7bb0': '#bc9560', '#7c6a9f': '#aa8048',
    'font: 600': 'font: 400', 'font-weight: 600': 'font-weight: 400',
    'border-radius: 24px;': 'border-radius: 28px 34px 27px 32px;',
    'border-radius: 14px;': 'border-radius: 21px 26px 22px 28px;',
    'border-radius: 8px;': 'border-radius: 14px;',
}.items():
    report = report.replace(old, new)
report += '''
.workbench-report .report-content { border: 0; box-shadow: none; background: transparent; }
.workbench-report .report-header { border-bottom: 1px dashed #dfc9a6; }
#reportNavigation a { border: 0; border-radius: 15px 12px 18px 13px; }
#reportNavigation a:hover { background: #f1e4cb; }
.workbench-report .report-text blockquote { border-left: 0; border-radius: 18px 23px 17px 24px; }
.workbench-report .report-btn { border-radius: 18px 22px 17px 21px; font-weight: 400; }
.workbench-report .report-btn-primary { box-shadow: 0 3px 0 #d5b98b; }
'''
responsive = '''
@media (max-width: 1120px) {
  .workbench-layout { grid-template-columns: minmax(0, 1.55fr) minmax(290px, .8fr); gap: 20px; }
  .agent-card-title { gap: 8px; }
  .agent-card-title h3 { font-size: 18px; }
  .agent-card-title p { font-size: 11px; }
  .workbench-agent-card { padding: 18px; }
}
@media (max-width: 980px) {
  .workbench-layout { grid-template-columns: minmax(0, 1fr); gap: 28px; }
  .agent-card-summary { position: static; grid-row: 1; min-height: 0; margin-top: 10px; }
  .summary-card-layout { display: grid; grid-template-columns: minmax(0, 1fr) 150px; align-items: center; gap: 18px; }
  .summary-companion { padding: 0; }
  .summary-companion span { display: none; }
  .agent-card-summary .agent-card-top { margin-bottom: 12px; }
}
@media (max-width: 720px) {
  .workbench-section { padding: 18px 14px; }
  .workbench-masthead { grid-template-columns: auto minmax(0, 1fr); gap: 12px 16px; padding-bottom: 18px; }
  .workbench-heading p { display: none; }
  .workbench-heading h1 { font-size: 25px; }
  .workbench-eyebrow { font-size: 10px; }
  .workbench-meta { grid-column: 2; display: flex; align-items: center; flex-wrap: wrap; justify-items: start; max-width: none; gap: 10px; }
  .workbench-time { font-size: 20px; }
  .workbench-status { padding: 4px 8px; font-size: 11px; }
  .agent-grid, .agents-grid { grid-template-columns: minmax(0, 1fr); gap: 18px; }
  .workbench-agent-card { min-height: 190px; padding: 20px; }
  .agent-card-title h3 { font-size: 21px; }
  .agent-card-title p { font-size: 12px; }
  .agent-card-title > div { min-width: 0; }
  .summary-card-layout { grid-template-columns: minmax(0, 1fr) 90px; gap: 10px; }
  .agent-card-summary { min-height: 0; }
  .agent-card-summary .agent-card-title h3 { font-size: 24px; }
  .agent-card-summary .agent-summary { font-size: 14px; margin-top: 12px; }
  .agent-card-summary .agent-monogram { display: none; }
  .market-overview { padding: 20px; }
  .market-overview .market-header { align-items: center; flex-direction: row; gap: 10px; }
  .market-overview .market-header > div { gap: 7px; }
  .market-overview .market-header h2 { font-size: 20px; }
  #marketTradeDate { font-size: 10px; }
  .market-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 20px; }
  .workbench-market-chart { height: 250px; }
  .workbench-report { grid-template-columns: minmax(0, 1fr); gap: 20px; margin-top: 24px; padding: 22px 16px; }
  .workbench-report .report-header { padding-bottom: 20px; }
  .workbench-report .report-title { font-size: 27px; }
  #reportNavigation { position: static; display: flex; gap: 8px; max-height: none; padding: 0 0 8px; overflow-x: auto; }
  #reportNavigation::before { display: none; }
  #reportNavigation a { flex: 0 0 auto; gap: 7px; padding: 9px 12px; background: #f3e9d5; white-space: nowrap; font-size: 12px; }
  .workbench-report .report-content { padding: 0 6px; }
  .workbench-report .report-analysis-block { padding: 20px 0; }
  .workbench-report .report-section-title { margin-bottom: 20px; font-size: 22px; }
  .workbench-report .report-text { font-size: 15px; line-height: 1.9; }
  .workbench-report .report-text blockquote { padding: 16px; }
  .workbench-report .report-text :is(th, td) { padding: 11px 12px; }
  .workbench-report .report-actions { grid-column: auto; }
  .workbench-report .report-btn { justify-content: center; min-height: 44px; padding: 12px 18px; font-size: 13px; }
}
@media (max-width: 430px) {
  .workbench-heading h1 { font-size: 23px; }
  .workbench-back { min-width: 44px; padding: 0 12px; }
  .workbench-back span:last-child { display: none; }
  .workbench-agent-card { padding: 18px; }
  .workspace-intro h2 { font-size: 20px; }
  .workspace-caption { font-size: 11px; }
  .market-overview .market-header { align-items: start; }
  #marketTradeDate { max-width: 100px; text-align: right; line-height: 1.8; }
  .market-metrics dd { font-size: 20px; }
}
@media (prefers-reduced-motion: reduce) {
  .workbench-section.active, .workbench-agent-card, .agent-card, .market-loading i,
  .status-indicator-dot, .workbench-back { animation: none !important; transition: none !important; }
  .workbench-agent-card:hover, .workbench-back:hover { transform: none; }
}
'''
sheet.write_text((root / 'output/cozy-theme.css').read_text(encoding='utf-8') + '\n' + report + '\n' + responsive, encoding='utf-8')

script = root / 'frontend/workbench.js'
js = script.read_text(encoding='utf-8')
for old, new in {
    '#91b7a1': '#bac1a5', '#dfa4a4': '#dfb8a3', '#708077': '#a48a68',
    'rgba(80,119,99,.06)': 'rgba(170,130,70,.07)',
    'rgba(80,119,99,.14)': 'rgba(170,130,70,.14)',
    '#64977d': '#8b9a7b', '#cc8585': '#c99478', '#8c7bb0': '#b28b45',
    '#6f9aa6': '#c69b7c',
}.items():
    js = js.replace(old, new)
js = js.replace("textColor: '#a48a68'", "textColor: '#a48a68', fontFamily: '\"DM Sans\", \"FINEX Notes\", sans-serif'")
script.write_text(js, encoding='utf-8')
