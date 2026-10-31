import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_client_update import build


class UpdatePackageTests(unittest.TestCase):
    def test_manifest_targets_exe_asset_and_matches_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            exe = base / 'game.exe'
            exe.write_bytes(b'MZtest')
            update_zip, install_zip, manifest_file = build(exe, '2.5.0', base / 'out')
            manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
            self.assertEqual(
                manifest['package_url'],
                'https://github.com/ghostkillerr/dragonpong-clone/releases/download/'
                'v2.5.0/DragonPongClone_client_v2.5.0.zip',
            )
            self.assertEqual(manifest['sha256'], hashlib.sha256(update_zip.read_bytes()).hexdigest())
            with zipfile.ZipFile(update_zip) as archive:
                self.assertEqual(archive.namelist(), ['DragonPongClone.exe'])
            with zipfile.ZipFile(install_zip) as archive:
                self.assertEqual(archive.read('client_version.txt'), b'2.5.0')
                self.assertNotIn('reference_sounds/', ''.join(archive.namelist()))


if __name__ == '__main__':
    unittest.main()
