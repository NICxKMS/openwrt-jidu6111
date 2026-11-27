#!/usr/bin/env python3
"""Assemble and verify release assets from OpenWrt build outputs."""

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from release_feed import extract_feed
from release_storage import build_root

BOARD = 'jiorouter,ax6000-jidu6111'
ARCHITECTURE = 'aarch64_cortex-a53'
DEVICE = 'jiorouter_ax6000-jidu6111'
RADIOS = {'dual-band': DEVICE, 'wcss-off': f'{DEVICE}-wcss-off'}
BUILD_PROFILES = ('gcc-kernel', 'clang-thinlto')
FILE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+~-]*\Z')
COMMIT = re.compile(r'[a-f0-9]{40}\Z')


def command(*args, **kwargs):
    return subprocess.check_output(args, **kwargs)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as contents:
        for chunk in iter(lambda: contents.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def output_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def safe_file(directory, name):
    if not isinstance(name, str) or not FILE_NAME.fullmatch(name):
        raise ValueError(f'Invalid artifact name {name!r}')
    path = directory / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Missing regular artifact {name}')
    return path


def pack_feed(repository, archive):
    packages = sorted(repository.glob('*.apk'))
    index = repository / 'packages.adb'
    if not packages or not index.is_file():
        raise ValueError(f'Incomplete APK repository at {repository}')
    with archive.open('wb') as output, gzip.GzipFile(fileobj=output, filename='', mode='wb',
                                                      mtime=0, compresslevel=1) as compressed, \
            tarfile.open(fileobj=compressed, mode='w') as bundle:
        for path in [index, *packages]:
            if not FILE_NAME.fullmatch(path.name) or not path.is_file():
                raise ValueError(f'Invalid APK repository file {path.name!r}')
            with path.open('rb') as contents:
                member = tarfile.TarInfo(path.name)
                member.size = path.stat().st_size
                member.mode = 0o644
                bundle.addfile(member, contents)


def installed_packages(database):
    result = {}
    for block in database.split('\n\n'):
        fields = {line[0]: line[2:] for line in block.splitlines() if line[1:2] == ':'}
        if 'P' not in fields:
            continue
        if not {'V', 'A'} <= fields.keys() or fields['P'] in result:
            raise ValueError('Invalid installed APK database')
        result[fields['P']] = (fields['V'], fields['A'])
    return result


def validate_index(packages, kernel, architecture):
    kernels = {(package['version'], package.get('arch')) for package in packages
               if package['name'] == 'kernel'}
    if kernels != {(kernel, architecture)} or not re.fullmatch(r'[^~]+~[A-Fa-f0-9]+-r\d+', kernel):
        raise ValueError('The signed index does not match the complete image kernel ABI')
    for package in packages:
        name = package['name']
        if package.get('arch') not in {architecture, 'noarch', 'all'}:
            raise ValueError(f'Wrong APK architecture for {name}')
        dependencies = [dep for dep in package.get('depends', []) if dep.startswith('kernel=')]
        if name.startswith('kmod-') and dependencies != [f'kernel={kernel}']:
            raise ValueError(f'Wrong kernel ABI for {name}')


def inspect_image(path, temp):
    # Both radio variants deliberately use the same upgrade board identity.
    prefix = f'sysupgrade-{DEVICE}'
    with tarfile.open(path, 'r:') as image:
        control = image.getmember(f'{prefix}/CONTROL')
        kernel = image.getmember(f'{prefix}/kernel')
        root = image.getmember(f'{prefix}/root')
        if not all(member.isfile() and member.size > 0 for member in (control, kernel, root)):
            raise ValueError(f'Invalid OpenWrt sysupgrade image {path.name}')
        board = image.extractfile(control).read().decode('utf-8').strip()
        if board != f'BOARD={DEVICE}':
            raise ValueError(f'Wrong board in {path.name}')
        rootfs = temp / 'rootfs.squashfs'
        with image.extractfile(root) as contents, rootfs.open('wb') as output:
            shutil.copyfileobj(contents, output)
    try:
        def read_image(name):
            return command('unsquashfs', '-processors', '1', '-cat', rootfs, name)

        architecture = read_image('etc/apk/arch').decode('utf-8').strip()
        packages = installed_packages(read_image('lib/apk/db/installed').decode('utf-8'))
        key = read_image('etc/apk/keys/public-key.pem')
        release = read_image('etc/openwrt_release').decode('utf-8')
        revision = re.search(r"^DISTRIB_REVISION='([^']+)'$", release, flags=re.MULTILINE)
    finally:
        rootfs.unlink()
    if architecture != ARCHITECTURE or not key or packages['kernel'][1] != architecture or not revision:
        raise ValueError(f'Wrong package architecture, firmware revision or signing key in {path.name}')
    return architecture, packages, key, revision[1]


def check_profile(apk, folder, images, archive, *, check_installed=False):
    with tempfile.TemporaryDirectory(prefix='jidu6111-verify-') as staging:
        staging = Path(staging)
        installed = {}
        image_hashes = set()
        key = identity = None
        for image in images:
            radio = image['radio']
            if radio not in RADIOS or radio in installed:
                raise ValueError(f'Duplicate or unsupported radio {radio!r}')
            path = safe_file(folder, image['file'])
            image_hash = sha256(path)
            if image_hash in image_hashes:
                raise ValueError('Two radio variants reference the same binary')
            image_hashes.add(image_hash)
            architecture, packages, embedded, revision = inspect_image(path, staging)
            current = (architecture, packages['kernel'][0], hashlib.sha256(embedded).hexdigest(), revision)
            if identity is not None and current != identity:
                raise ValueError('The two images cannot share a signed feed')
            key, identity = embedded, current
            installed[radio] = packages
        if identity is None:
            raise ValueError('A signed feed requires at least one matching firmware image')
        architecture, kernel, fingerprint, revision = identity
        key_directory = staging / 'etc/apk/keys'
        key_directory.mkdir(parents=True)
        (key_directory / 'public-key.pem').write_bytes(key)
        feed_directory = staging / 'feed'
        extract_feed(safe_file(folder, archive), feed_directory)
        apk_paths = sorted(feed_directory.glob('*.apk'))
        index = feed_directory / 'packages.adb'
        apk_verify = (apk, '--quiet', '--root', staging, '--keys-dir', 'etc/apk/keys')
        command(*apk_verify, 'verify', index)
        for start in range(0, len(apk_paths), 100):
            command(*apk_verify, 'verify', *apk_paths[start:start + 100])
        packages = json.loads(command(apk, 'adbdump', '--format', 'json', index))['packages']
        validate_index(packages, kernel, architecture)
        regenerated = staging / 'regenerated.adb'
        command(*apk_verify, 'mkndx', '--output', regenerated, *apk_paths)
        regenerated_packages = json.loads(command(apk, 'adbdump', '--format', 'json', regenerated))['packages']
        if packages != regenerated_packages:
            raise ValueError('The package files do not match the signed APK index')
        if check_installed:
            available = {(package['name'], package['version'], package['arch']) for package in packages}
            for radio, image_packages in installed.items():
                missing = sorted(name for name, (version, arch) in image_packages.items()
                                 if (name, version, arch) not in available)
                if missing:
                    raise ValueError(f'Packages missing from the {radio} image feed: {", ".join(missing)}')
    return {'architecture': architecture, 'kernel': kernel, 'key_sha256': fingerprint,
            'firmware_revision': revision}, installed


def describe_assets(folder):
    return {path.name: {'sha256': sha256(path), 'size': path.stat().st_size}
            for path in sorted(folder.iterdir()) if path.is_file() and not path.is_symlink()
            and path.name != 'release-manifest.json'}


def collect(args):
    profile = args.profile
    build = args.openwrt / f'bin-{profile}'
    target = build / 'targets/qualcommbe/ipq95xx'
    profiles = json.loads((target / 'profiles.json').read_text(encoding='utf-8'))
    apk = args.openwrt / 'staging_dir/host/bin/apk'
    images = []
    for radio, device in RADIOS.items():
        info = profiles['profiles'][device]
        matches = [image for image in info['images'] if image['type'] == 'sysupgrade'
                   and image['filesystem'] == 'squashfs']
        if info['supported_devices'] != [BOARD] or len(matches) != 1:
            raise ValueError(f'Invalid OpenWrt image metadata for {device}')
        original = safe_file(target, matches[0]['name'])
        if sha256(original) != matches[0]['sha256']:
            raise ValueError(f'OpenWrt image checksum differs for {original.name}')
        filename = f'jidu6111-{profile}-{radio}-sysupgrade.bin'
        shutil.copyfile(original, args.output / filename)
        images.append({'radio': radio, 'file': filename, 'hardware_verified': False})
    feed = f'jidu6111-{profile}-feed.tar.gz'
    pack_feed(build / 'repository', args.output / feed)
    identity, installed = check_profile(apk, args.output, images, feed, check_installed=True)
    public = args.openwrt / 'public-key.pem'
    if identity['key_sha256'] != sha256(public):
        raise ValueError('Image key differs from the explicitly selected build key')
    if identity['architecture'] != profiles['arch_packages']:
        raise ValueError('OpenWrt image metadata reports a different package architecture')
    buildinfo = f'jidu6111-{profile}-buildinfo.json'
    tool_versions = dict(args.tool_version or [])

    def portable(text):
        return (text.replace(f'file://{args.openwrt.parent}', 'https://github.com/NICxKMS/openwrt-jidu6111.git')
                .replace(str(args.openwrt), '${OPENWRT_DIR}'))

    output_json(args.output / buildinfo, {
        'source_commit': args.commit,
        'openwrt_commit': command('git', '-C', args.openwrt, 'rev-parse', 'HEAD', text=True).strip(),
        'feed_revisions': {path.name: command('git', '-C', path, 'rev-parse', 'HEAD', text=True).strip()
                           for path in sorted((args.openwrt / 'feeds').iterdir())
                           if path.is_dir() and (path / '.git').exists()},
        'buildinfo': {name: portable((target / name).read_text(encoding='utf-8'))
                      for name in ('config.buildinfo', 'version.buildinfo', 'feeds.buildinfo')},
        'resolved_config': portable((args.openwrt / '.config').read_text(encoding='utf-8')),
        'kernel': profiles['linux_kernel'],
        'installed_packages': installed,
        'tool_versions': tool_versions,
        'build_host': {'system': platform.system(), 'machine': platform.machine()},
        'verification': 'build-verified',
    })
    output_json(args.profile_record, {'id': profile, 'board': BOARD, 'feed': feed,
                                      'images': images, 'buildinfo': buildinfo, **identity})


def manifest(args):
    records = [json.loads(record.read_text(encoding='utf-8')) for record in args.profile_record]
    output_json(args.output / 'release-manifest.json', {
        'schema': 1, 'source_commit': args.commit, 'profiles': records, 'assets': describe_assets(args.output),
    })


def bootstrap(args):
    commits = [args.commit, args.firmware_source, *([args.package_source] if args.package_source else [])]
    if not all(COMMIT.fullmatch(commit) for commit in commits):
        raise ValueError('Bootstrap source revisions must be full Git commit SHAs')
    if args.output.exists() or args.output.is_symlink():
        raise ValueError(f'Output already exists: {args.output}')
    root = build_root().resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.output.parent.stat().st_dev != root.stat().st_dev:
        raise ValueError('The build workspace and output must be on the same filesystem')
    # Match the build cleanup namespace and hold the directory lock for the entire verification.
    with tempfile.TemporaryDirectory(prefix='build.', dir=root) as workspace:
        workspace = Path(workspace)
        fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            (workspace / '.jidu6111-owned').touch(exist_ok=False)
            target = workspace / 'assets'
            target.mkdir()
            filename = 'jidu6111-legacy-dual-band-sysupgrade.bin'
            feed = 'jidu6111-legacy-feed.tar.gz'
            images = [{'radio': 'dual-band', 'file': filename, 'hardware_verified': False}]
            shutil.copyfile(args.image, target / filename)
            pack_feed(args.feed, target / feed)
            identity, installed = check_profile(args.apk, target, images, feed)
            if identity['firmware_revision'] != args.expected_revision:
                raise ValueError(f'Expected {args.expected_revision}, got {identity["firmware_revision"]}')
            buildinfo = 'jidu6111-legacy-buildinfo.json'
            output_json(target / buildinfo, {
                'firmware_source': args.firmware_source,
                'package_source': args.package_source or args.firmware_source,
                'buildinfo': {label: path.read_text(encoding='utf-8') for label, path in {
                    'config.buildinfo': args.config_buildinfo,
                    'feeds.buildinfo': args.feeds_buildinfo,
                    'version.buildinfo': args.version_buildinfo,
                }.items() if path is not None},
                'installed_image_packages': installed,
                'verification': 'existing-bytes-verified',
            })
            output_json(target / 'release-manifest.json', {
                'schema': 1, 'source_commit': args.commit, 'assets': describe_assets(target),
                'profiles': [{'id': 'legacy', 'board': BOARD, 'feed': feed, 'images': images,
                              'buildinfo': buildinfo, **identity}],
            })
            command('mv', '-nT', '--', target, args.output)
            if target.is_dir():
                raise ValueError(f'Output appeared while verifying: {args.output}')
        finally:
            os.close(fd)


def verify(args):
    document = json.loads(safe_file(args.directory, 'release-manifest.json').read_text(encoding='utf-8'))
    if document['schema'] != 1 or not document['profiles']:
        raise ValueError('Invalid release manifest')
    for name, metadata in document['assets'].items():
        path = safe_file(args.directory, name)
        if metadata['size'] != path.stat().st_size or metadata['sha256'] != sha256(path):
            raise ValueError(f'Artifact size or SHA-256 differs for {name}')
    for profile in document['profiles']:
        if profile['board'] != BOARD:
            raise ValueError('Unexpected release board')
        for asset in [profile['feed'], *(image['file'] for image in profile['images'])]:
            if asset not in document['assets']:
                raise ValueError(f'Missing manifest entry for {asset}')
        identity, _ = check_profile(args.apk, args.directory, profile['images'], profile['feed'])
        if any(profile.get(field, value if field == 'firmware_revision' else None) != value
               for field, value in identity.items()):
            raise ValueError(f'Manifest identity mismatch for {profile["id"]}')
        print(f'Verified {profile["id"]} firmware and APK feed for {identity["kernel"]}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest='operation', required=True)
    collect_parser = operations.add_parser('collect')
    collect_parser.add_argument('--openwrt', type=Path, required=True)
    collect_parser.add_argument('--output', type=Path, required=True)
    collect_parser.add_argument('--profile-record', type=Path, required=True)
    collect_parser.add_argument('--profile', choices=BUILD_PROFILES, required=True)
    collect_parser.add_argument('--commit', required=True)
    collect_parser.add_argument('--tool-version', action='append', nargs=2)
    manifest_parser = operations.add_parser('manifest')
    manifest_parser.add_argument('--output', type=Path, required=True)
    manifest_parser.add_argument('--commit', required=True)
    manifest_parser.add_argument('--profile-record', action='append', type=Path, required=True)
    verify_parser = operations.add_parser('verify')
    verify_parser.add_argument('--directory', type=Path, required=True)
    verify_parser.add_argument('--apk', required=True)
    bootstrap_parser = operations.add_parser('bootstrap')
    bootstrap_parser.add_argument('--output', type=Path, required=True)
    bootstrap_parser.add_argument('--apk', required=True)
    bootstrap_parser.add_argument('--commit', required=True)
    bootstrap_parser.add_argument('--firmware-source', required=True)
    bootstrap_parser.add_argument('--package-source')
    bootstrap_parser.add_argument('--expected-revision', default='r0+38470-c3af7ee2f2')
    bootstrap_parser.add_argument('--image', type=Path, required=True)
    bootstrap_parser.add_argument('--feed', type=Path, required=True)
    bootstrap_parser.add_argument('--config-buildinfo', type=Path)
    bootstrap_parser.add_argument('--feeds-buildinfo', type=Path)
    bootstrap_parser.add_argument('--version-buildinfo', type=Path)
    args = parser.parse_args()
    try:
        {'collect': collect, 'manifest': manifest, 'verify': verify, 'bootstrap': bootstrap}[args.operation](args)
    except (KeyError, OSError, RuntimeError, ValueError, tarfile.TarError) as error:
        parser.exit(1, f'{error}\n')
    except subprocess.CalledProcessError as error:
        details = error.output or ''
        if isinstance(details, bytes):
            details = details.decode('utf-8', errors='replace')
        details = details.strip()
        parser.exit(1, f'Artifact verification command failed: {error.cmd[0]}\n{details}\n')


if __name__ == '__main__':
    main()
