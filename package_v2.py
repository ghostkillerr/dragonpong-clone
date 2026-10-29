"""Build separate source and local reference archives from explicit allowlists."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE.parent
LOCAL = BASE / 'release_local_v2'
LOCAL.mkdir(exist_ok=True)
for name in ('start_clone.bat', 'OYNA.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'PARITY.md'):
    shutil.copy2(BASE / name, LOCAL / name)
shutil.copy2(BASE / 'dist/DragonPongClone.exe', LOCAL / 'DragonPongClone.exe')
shutil.copytree(BASE / 'reference_sounds', LOCAL / 'reference_sounds', dirs_exist_ok=True)
source = [p for folder in ('dragonpong', 'tests') for p in (BASE / folder).glob('*.py')]
source += [BASE / name for name in (
    'run_offline.py', 'prepare_reference_sounds.py', 'verify_native.py', 'package_v2.py', 'verify_public.py',
    'requirements.txt', 'requirements-dev.txt', 'start_clone.bat', 'start_server.bat',
    'build_exe.bat', 'README.md', 'OYNA.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
    'PARITY.md', 'REGRESSION.md', 'native_verification.json', '.gitignore',
    'assets/mit-kemar-compact.zip')]
archives = []
for name, root, paths in (
    ('DragonPongClone_source_v2.zip', BASE, source),
    ('DragonPongClone_local_v2.zip', LOCAL, [p for p in LOCAL.rglob('*') if p.is_file()])):
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
(BASE / 'packages_v2.json').write_text(json.dumps(archives, indent=2), encoding='utf-8')
print(json.dumps(archives, indent=2))
