from pathlib import Path
import re, subprocess
root = Path(r'C:/Users/Lukesu/.codex/worktrees/readme-v2/Finance1')
p = root / 'README.md'
s = p.read_text(encoding='utf-8').replace('node --test tests/frontend/*.cjs', 'node --test tests/frontend/test_workbench.cjs')
p.write_text(s, encoding='utf-8')
links = re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', s)
missing = [x for x in links if '://' not in x and not x.startswith('#') and not (root / x.split('#')[0]).exists()]
assert not missing, missing
assert s.count('```') % 2 == 0
for path in ['scripts/start_server.bat', 'scripts/start_server.sh', 'scripts/setup_pdf.ps1', 'scripts/generate_pdf.py', 'scripts/run_ci_tests.py', 'agents/.env.example', 'requirements-test.txt', 'tests/frontend/test_workbench.cjs']:
    assert (root / path).is_file(), path
print('PASS: relative links, code fences, referenced scripts and test paths')
subprocess.run(['git', '-C', str(root), 'diff', '--check'], check=True)
subprocess.run(['git', '-C', str(root), 'status', '--short'], check=True)
subprocess.run(['git', '-C', str(root), 'branch', '--show-current'], check=True)
subprocess.run(['git', '-C', str(root), 'diff', '--stat'], check=True)
