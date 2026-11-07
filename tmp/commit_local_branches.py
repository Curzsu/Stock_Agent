"""Commit prepared functional snapshots without switching the running checkout."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
BUNDLES=ROOT/'tmp/local-commit-bundles'
manifest=json.loads((BUNDLES/'manifest.json').read_text(encoding='utf-8'))
BASE=manifest['base']
groups=[('langsmith','codex/integrate-langsmith','commit-langsmith.txt'),
        ('analysis','codex/fix-analysis-timeouts','commit-analysis.txt'),
        ('chart','codex/align-research-kline','commit-chart.txt')]

def git(*args, data=None, env=None):
    result=subprocess.run(['git',*args],cwd=ROOT,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    if result.returncode:
        raise RuntimeError('git '+str(args[:2])+': '+result.stderr.decode('utf-8',errors='replace'))
    return result.stdout.decode('utf-8').strip()

for group,branch,message_file in groups:
    assert git('rev-parse',branch)==BASE, 'Branch changed: '+branch
    print(branch+': '+(ROOT/'tmp'/message_file).read_text(encoding='utf-8').splitlines()[0])
assert git('symbolic-ref','--short','HEAD')=='codex/align-research-kline'
assert not git('diff','--cached','--name-only'), 'Pre-existing staged changes need review'
for path,digest in manifest['working_hashes'].items():
    assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest,'File changed since preview: '+path
if '--apply' not in sys.argv:
    print('Preview complete; no refs or working files changed.')
    raise SystemExit(0)

parent=BASE
results=[]
for group,branch,message_file in groups:
    index=ROOT/'tmp'/('commit-index-'+uuid.uuid4().hex)
    env={**os.environ,'GIT_INDEX_FILE':str(index)}
    git('read-tree',parent,env=env)
    for path in manifest['groups'][group]:
        blob=git('hash-object','-w','--path='+path,'--stdin',data=(BUNDLES/group/path).read_bytes(),env=env)
        git('update-index','--add','--cacheinfo','100644',blob,path,env=env)
    tree=git('write-tree',env=env)
    assert tree!=git('rev-parse',parent+'^{tree}'),'Empty commit: '+branch
    message=(ROOT/'tmp'/message_file).read_bytes()
    args=['commit-tree',tree,'-p',parent]
    if subprocess.run(['git','config','--bool','commit.gpgsign'],cwd=ROOT,capture_output=True,text=True).stdout.strip()=='true':
        args.append('-S')
    commit=git(*args,data=message)
    results.append({'branch':branch,'commit':commit,'parent':parent,'tree':tree})
    parent=commit

# All three ref updates succeed together, or none do. Keep the worktree files intact.
result_file=BUNDLES/'results.json'
result_file.write_text(json.dumps({'applied':False,'commits':results},ensure_ascii=False,indent=2),encoding='utf-8')
transaction='start\n'+''.join(f"update refs/heads/{r['branch']} {r['commit']} {BASE}\n" for r in results)+'prepare\ncommit\n'
git('update-ref','-m','commit: 按功能整理本地待提交改动','--stdin',data=transaction.encode('utf-8'))
git('read-tree',parent)
assert not git('status','--porcelain=v1','-uall'),'Worktree differs from committed snapshot; inspect before further actions'
result_file.write_text(json.dumps({'applied':True,'commits':results},ensure_ascii=False,indent=2),encoding='utf-8')
for r in results:
    print(r['branch'],r['commit'][:8])
