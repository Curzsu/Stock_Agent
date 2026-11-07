import re
from pathlib import Path
ROOT=Path('C:/Users/Lukesu/.codex/worktrees/readme-v2/Finance1')
missing=[]
for name in ['README.md','docs/development.md']:
    p=ROOT/name
    text=p.read_text(encoding='utf-8')
    links=re.findall(r'\]\(([^)]+)\)',text)+re.findall(r'src="([^"]+)"',text)
    for link in links:
        if '://' in link or link.startswith('#'):
            continue
        if not (p.parent/link.split('#')[0]).exists():
            missing.append(name+': '+link)
assert not missing,missing
image=(ROOT/'images-README/image-20261102135108623.png').read_bytes()
assert image.startswith(bytes([137,80,78,71,13,10,26,10]))
print('README links and PNG verified; bytes:',len(image))
