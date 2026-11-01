"""Deploy the source clone with staging, an empty-room guard and rollback."""

from __future__ import annotations

import getpass
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent
HOST = "ekransizoyuncular.gen.tr"


def command(ssh: paramiko.SSHClient, text: str) -> None:
    _, stdout, stderr = ssh.exec_command(text, timeout=20)
    output = stdout.read().decode(errors="replace").strip()
    errors = stderr.read().decode(errors="replace").strip()
    status = stdout.channel.recv_exit_status()
    print(text, "exit", status)
    if output:
        print(output)
    if errors:
        print(errors)
    if status:
        raise RuntimeError(text)


def main() -> None:
    password = getpass.getpass("VPS root SSH parolası: ")
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(HOST, username="root", password=password, look_for_keys=False,
                allow_agent=False, timeout=15, auth_timeout=15)
    try:
        command(ssh, "mkdir -p /opt/dragonpong/clone-next/dragonpong")
        with ssh.open_sftp() as sftp:
            for filename in ("__init__.py", "engine.py", "netplay.py", "server.py"):
                sftp.put(str(ROOT / "dragonpong" / filename),
                         f"/opt/dragonpong/clone-next/dragonpong/{filename}")
        command(ssh, "python3 -m py_compile /opt/dragonpong/clone-next/dragonpong/*.py")
        command(ssh, "PYTHONPATH=/opt/dragonpong/clone-next python3 -c 'from dragonpong.server import Server; Server()'")
        command(ssh, """python3 - <<'PY'
import json, socket, shutil, subprocess, time
from pathlib import Path
def rooms():
    with socket.create_connection(('127.0.0.1',8870),3) as sock:
        sock.sendall(b'{"type":"rooms"}\\n')
        return json.loads(sock.makefile('rb').readline())
if rooms()['rooms']:
    raise RuntimeError('Active rooms exist; deployment not applied')
root=Path('/opt/dragonpong/clone/dragonpong')
backup=Path('/opt/dragonpong/clone-backup-'+str(time.time_ns()))
shutil.copytree(root,backup)
print('Backup:',backup)
subprocess.run(['systemctl','stop','dragonpong-clone.service'],check=True)
try:
    for path in Path('/opt/dragonpong/clone-next/dragonpong').glob('*.py'):
        shutil.copy2(path,root/path.name)
    subprocess.run(['systemctl','start','dragonpong-clone.service'],check=True)
    for attempt in range(30):
        try:
            listing = rooms()
            if 'strike_ref_v1' not in listing.get('features', []):
                raise RuntimeError('Strike reference feature is unavailable')
            break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError('Health probe failed')
    subprocess.run(['systemctl','is-active','dragonpong-clone.service'],check=True)
except Exception:
    subprocess.run(['systemctl','stop','dragonpong-clone.service'],check=True)
    for path in backup.glob('*.py'):
        shutil.copy2(path,root/path.name)
    subprocess.run(['systemctl','start','dragonpong-clone.service'],check=True)
    print('Rolled back to',backup)
    raise
PY""")
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
