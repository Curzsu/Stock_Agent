"""Check the tracing-only commit as an independent exported source tree."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BUNDLES=ROOT/'tmp/local-commit-bundles'
CHECK=ROOT/'tmp/local-commit-langsmith-check'
CHECK.mkdir(exist_ok=True)
archive=subprocess.check_output(['git','archive','--format=zip','d0ee479'],cwd=ROOT)
with zipfile.ZipFile(io.BytesIO(archive)) as z:
    z.extractall(CHECK)
shutil.copytree(BUNDLES/'langsmith',CHECK,dirs_exist_ok=True)
env={**os.environ,'PYTHON_DOTENV_DISABLED':'1','LANGSMITH_TRACING':'false','USE_TORCH':'0','USE_TF':'0','PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
script="""import sys
from pathlib import Path
sys.path.insert(0,str(Path('scripts').resolve()))
import run_ci_tests as r
raise SystemExit(r.run_suite([Path('tests/test_observability.py'),Path('tests/test_workflow_builder.py'),Path('tests/test_analysis_session_api.py')]))
"""
with (ROOT/'logs/local-commit-langsmith-tests.log').open('w',encoding='utf-8') as out:
    result=subprocess.run([str(ROOT/'venv/Scripts/python.exe'),'-c',script],cwd=CHECK,env=env,stdout=out,stderr=subprocess.STDOUT)
print('Tracing-only snapshot exit:',result.returncode)
raise SystemExit(result.returncode)
