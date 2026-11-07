from pathlib import Path
import re
import subprocess
import tinycss2 as css

root = Path.cwd()
original_html = subprocess.check_output(['git', 'show', 'v2.0:frontend/index.html']).decode('utf-8')
original_css = subprocess.check_output(['git', 'show', 'v2.0:frontend/workbench.css']).decode('utf-8')
Path('output/v2-index.html').write_text(original_html, encoding='utf-8')
Path('output/v2-workbench.css').write_text(original_css, encoding='utf-8')
inline = re.search(r'<style>(.*?)</style>', original_html, re.S)[1]
paint = {'color', 'background', 'background-color', 'background-image', 'border-color', 'outline-color', 'text-decoration-color', 'scrollbar-color'}

def selectors(tokens):
    result, part = [], []
    for token in tokens:
        if token.type == 'literal' and token.value == ',':
            result.append(css.serialize(part).strip())
            part = []
        else:
            part.append(token)
    result.append(css.serialize(part).strip())
    return result

def declarations(rule):
    return css.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)

baseline = {}
for rule in css.parse_stylesheet(inline + '\n' + original_css, skip_comments=True, skip_whitespace=True):
    if rule.type == 'qualified-rule':
        values = {d.name: css.serialize(d.value).strip() for d in declarations(rule) if d.type == 'declaration'}
        for selector in selectors(rule.prelude):
            baseline.setdefault(selector, {}).update(values)

sheet = Path('frontend/workbench.css')
before = sheet.read_text(encoding='utf-8')
Path('output/before-v2-palette.css').write_text(before, encoding='utf-8')
rules = css.parse_stylesheet(before, skip_comments=True, skip_whitespace=True)
output = []
in_workbench = False
shadow_colors = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)')

for rule in rules:
    if rule.type != 'qualified-rule':
        output.append(css.serialize([rule]))
        continue
    names = selectors(rule.prelude)
    if names == ['.workbench-section']:
        in_workbench = True
    if not in_workbench and any(x in names for x in ['body', '.noise-overlay', '.hero-bg', '.hero-bg::before']):
        # Let v2's own background layers and their original colors apply again.
        continue
    target = {}
    for selector in names:
        target.update(baseline.get(selector, {}))
    updated = []
    for d in declarations(rule):
        if d.type != 'declaration':
            continue
        name, value = d.name, css.serialize(d.value).strip()
        if names == [':root']:
            if name.startswith('--wb-') and name in baseline[':root'] and name not in ('--wb-sans', '--wb-serif'):
                value = baseline[':root'][name]
            elif name in ('--black', '--cream', '--warm-bg', '--gold', '--gold-light', '--gold-glow'):
                continue  # The original inline :root owns all landing-page colors.
        elif not in_workbench:
            if name in paint:
                continue  # Inherit the exact original inline styles, including hover states.
            if name == 'box-shadow':
                value = target.get(name, 'none')
        else:
            if name in paint:
                if name in target:
                    value = target[name]
                elif name in ('background', 'background-color'):
                    if '.agent-card-summary' in names:
                        continue  # Original summary inherits the shared agent surface.
                    value = 'transparent'
                elif name == 'color':
                    if any('.agent-card-title h3' in x for x in names):
                        value = 'var(--wb-ink)'
                    elif any('.agent-summary' in x for x in names):
                        value = baseline['.agent-summary']['color']
                    else:
                        value = 'var(--wb-muted)'
                elif name == 'scrollbar-color':
                    value = 'var(--wb-line) transparent'
            elif name == 'box-shadow':
                old_colors = shadow_colors.findall(target.get(name, ''))
                if old_colors:
                    color_iter = iter(old_colors)
                    value = shadow_colors.sub(lambda m: next(color_iter, old_colors[-1]), value)
                else:
                    value = 'none'
            elif name == '--note-color':
                value = 'var(--wb-paper-raised)'
            elif name == '--note-ink':
                value = 'var(--wb-gold)'
            elif name == '--note-tint':
                value = 'rgba(128, 97, 39, .09)'
            elif name in ('border', 'border-top', 'border-bottom', 'border-left', 'border-right') and shadow_colors.search(value):
                source = target.get(name, '')
                source_colors = shadow_colors.findall(source)
                value = shadow_colors.sub(lambda _: source_colors[0] if source_colors else 'var(--wb-line)', value)
        updated.append(f'{name}: {value}' + (' !important' if d.important else '') + ';')
    if updated:
        output.append(css.serialize(rule.prelude).strip() + ' {\n  ' + '\n  '.join(updated) + '\n}')

sheet.write_text('\n\n'.join(output) + '\n', encoding='utf-8')
script = Path('frontend/workbench.js')
original_js = subprocess.check_output(['git', 'show', 'v2.0:frontend/workbench.js']).decode('utf-8')
# The only non-palette change to chart creation is the previously approved UI font.
original_js = original_js.replace("textColor: '#74695b'", "textColor: '#74695b', fontFamily: '\"DM Sans\", \"FINEX Round\", sans-serif'")
script.write_text(original_js, encoding='utf-8')
print('Restored v2.0 palette and removed landing-page color overrides.')
