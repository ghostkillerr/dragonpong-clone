"""Build separate source and local reference archives from explicit allowlists."""
import hashlib
import json
import shutil
import zipfile
import argparse
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE.parent
parser = argparse.ArgumentParser()
parser.add_argument('--version', default='v2')
parser.add_argument('--exe', type=Path, default=BASE / 'dist/DragonPongClone.exe')
args = parser.parse_args()
VERSION = args.version
if not re.fullmatch(r'v[0-9]+(?:_[0-9]+)*', VERSION):
    raise ValueError('Invalid package version')
LOCAL = BASE / f'release_local_{VERSION}'
LOCAL.mkdir(exist_ok=True)
for name in ('start_clone.bat', 'update_launcher.ps1', 'OYNA.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'PARITY.md', 'PHYSICS_COMPARISON.md', 'V7_COMPARISON.md'):
    shutil.copy2(BASE / name, LOCAL / name)
parts = VERSION[1:].split('_')
(LOCAL / 'client_version.txt').write_text('.'.join((parts + ['0', '0'])[:3]), encoding='utf-8')
if args.exe.resolve() != (LOCAL / 'DragonPongClone.exe').resolve():
    shutil.copy2(args.exe, LOCAL / 'DragonPongClone.exe')
shutil.copytree(BASE / 'reference_sounds', LOCAL / 'reference_sounds', dirs_exist_ok=True)
source = [p for folder in ('dragonpong', 'tests') for p in (BASE / folder).glob('*.py')]
source += [BASE / name for name in (
    'run_offline.py', 'prepare_reference_sounds.py', 'verify_native.py', 'package_v2.py', 'build_client_update.py', 'verify_public.py',
    'verify_rallies.py', 'PHYSICS_COMPARISON.md', 'rally_baseline.json', 'rally_verification.json',
    'V7_COMPARISON.md', 'AGENTS.md',
    'requirements.txt', 'requirements-dev.txt', 'start_clone.bat', 'start_server.bat',
    'build_exe.bat', 'update_launcher.ps1', 'client_version.txt', 'update.json', 'README.md', 'OYNA.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
    'PARITY.md', 'REGRESSION.md', 'native_verification.json', '.gitignore',
    'assets/mit-kemar-compact.zip')]
archives = []
for name, root, paths in (
    (f'DragonPongClone_source_{VERSION}.zip', BASE, source),
    (f'DragonPongClone_local_{VERSION}.zip', LOCAL, [p for p in LOCAL.rglob('*') if p.is_file()])):
    target = OUT / name
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, path.relative_to(root).as_posix())
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        if 'source' in name:
            assert not any(n.lower().endswith(('.wav', '.exe')) for n in archive.namelist())
    archives.append({'file': name, 'bytes': target.stat().st_size,
                     'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
(BASE / f'packages_{VERSION}.json').write_text(json.dumps(archives, indent=2), encoding='utf-8')
print(json.dumps(archives, indent=2))
