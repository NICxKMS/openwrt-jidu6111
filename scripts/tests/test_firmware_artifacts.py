import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from firmware_artifacts import BOARD, check_profile, installed_packages, validate_index, verify


class FirmwareArtifactTests(unittest.TestCase):
    def test_installed_kernel_identity_preserves_complete_abi(self):
        database = 'P:kernel\nV:6.18.65~012345abcdef-r1\nA:aarch64_cortex-a53\n\n'
        packages = installed_packages(database)
        self.assertEqual(packages['kernel'], ('6.18.65~012345abcdef-r1', 'aarch64_cortex-a53'))

    def test_index_rejects_kernel_abi_mismatch(self):
        arch = 'aarch64_cortex-a53'
        index = [
            {'name': 'kernel', 'version': '6.18.65~abcdef-r1', 'arch': arch},
            {'name': 'kmod-foo', 'version': '6.18.65-r1', 'arch': arch,
             'depends': ['kernel=6.18.65~fedcba-r1']},
        ]
        with self.assertRaisesRegex(ValueError, 'kernel ABI'):
            validate_index(index, '6.18.65~abcdef-r1', arch)

    def test_index_accepts_compatible_modules_and_noarch_packages(self):
        arch = 'aarch64_cortex-a53'
        kernel = '6.18.65~abcdef-r1'
        index = [
            {'name': 'kernel', 'version': kernel, 'arch': arch},
            {'name': 'kmod-foo', 'version': '6.18.65-r1', 'arch': arch, 'depends': [f'kernel={kernel}']},
            {'name': 'luci-app-foo', 'version': '1.0-r1', 'arch': 'noarch'},
        ]
        validate_index(index, kernel, arch)

    def test_build_refuses_to_replace_existing_output(self):
        revision = subprocess.check_output(['git', '-C', str(SCRIPTS.parent), 'rev-parse', 'HEAD'], text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'existing'
            output.mkdir()
            marker = output / 'existing_asset'
            marker.write_text('keep this')
            result = subprocess.run(['bash', str(SCRIPTS / 'build-firmware.sh'), '--commit', revision,
                                     '--output', str(output), '--signing-key', '/nonexistent'],
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('already exists', result.stderr)
            self.assertEqual(marker.read_text(), 'keep this')

    def test_failed_source_preparation_cleans_its_workspace(self):
        commit = subprocess.check_output(['git', '-C', str(SCRIPTS.parent), 'rev-parse', 'HEAD'], text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            tools = parent / 'bin'
            tools.mkdir()
            make = tools / 'make'
            make.write_text(
                '#!/bin/sh\nset -eu\n'
                'case ":$PATH:" in *:./relative-bin:*|*:"/path with spaces":*) exit 70;; esac\n'
                'test "$(git -C "$2" rev-parse HEAD)" = "$CANDIDATE_COMMIT"\n'
                'grep -Fqx "src-git nicx_monitor file://$2^$CANDIDATE_COMMIT" "$2/sources/feeds.conf"\n'
                'printf "source preparation stopped\\n" >&2\nexit 73\n', encoding='utf-8',
            )
            make.chmod(0o700)
            unsquashfs = tools / 'unsquashfs'
            unsquashfs.write_text('#!/bin/sh\nexit 99\n', encoding='utf-8')
            unsquashfs.chmod(0o700)
            signing_key = parent / 'key.pem'
            signing_key.write_text('unused because source preparation fails')
            output = parent / 'release'
            builds = parent / 'builds'
            env = {**os.environ, 'PATH': f'{tools}:./relative-bin:/path with spaces:{os.environ["PATH"]}',
                   'JIDU6111_BUILD_ROOT': str(builds), 'CANDIDATE_COMMIT': commit}
            result = subprocess.run(['bash', str(SCRIPTS / 'build-firmware.sh'), '--commit', commit,
                                     '--profile', 'gcc-kernel', '--output', str(output),
                                     '--signing-key', str(signing_key)], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 73, result.stderr)
            self.assertIn('source preparation stopped', result.stderr)
            self.assertFalse(output.exists())
            self.assertEqual(list(builds.iterdir()), [])

    def test_profile_rejects_two_radio_variants_with_identical_image_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            images = [{'radio': radio, 'file': f'{radio}.bin'} for radio in ('dual-band', 'wcss-off')]
            for image in images:
                (folder / image['file']).write_bytes(b'identical')
            architecture = 'aarch64_cortex-a53'
            identity = (architecture, {'kernel': ('6.18.65~abcdef-r1', architecture)}, b'test-key', 'snapshot')
            with patch('firmware_artifacts.inspect_image', return_value=identity):
                with self.assertRaisesRegex(ValueError, 'same binary'):
                    check_profile('unused', folder, images, 'unused-feed.tar.gz')

    def test_verifier_rejects_invalid_schema_types_and_missing_revision(self):
        identity = {'architecture': 'aarch64_cortex-a53', 'kernel': '6.18.65~abcdef-r1',
                    'firmware_revision': 'r0+123-test', 'key_sha256': '0' * 64}
        for schema, revision, error in ((True, 'r0+123-test', 'Invalid release manifest'),
                                        (1.0, 'r0+123-test', 'Invalid release manifest'),
                                        (1, None, 'Manifest identity mismatch')):
            with self.subTest(schema=schema, revision=revision), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                profile = {'id': 'legacy', 'board': BOARD, 'architecture': identity['architecture'],
                           'kernel': identity['kernel'], 'key_sha256': identity['key_sha256'],
                           'feed': 'test-feed.tar.gz', 'images': []}
                if revision is not None:
                    profile['firmware_revision'] = revision
                (directory / profile['feed']).write_bytes(b'test')
                (directory / 'release-manifest.json').write_text(json.dumps({
                    'schema': schema, 'profiles': [profile], 'assets': {
                        profile['feed']: {'size': 4, 'sha256': '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08'},
                    },
                }), encoding='utf-8')
                with patch('firmware_artifacts.check_profile', return_value=(identity, {})):
                    with self.assertRaisesRegex(ValueError, error):
                        verify(SimpleNamespace(directory=directory, apk='unused'))
