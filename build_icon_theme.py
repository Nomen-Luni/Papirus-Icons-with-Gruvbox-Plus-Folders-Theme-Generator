#!/usr/bin/env python3
"""Build Papirus Dark with Gruvbox Dark folders; Python 3.8+, no dependencies.

Run: python3 build_icon_theme.py
Then select 'Papirus Dark with Gruvbox folders' in KDE's icon settings.
The output contains folder overrides and inherits the installed Papirus theme.
Rerun after Gruvbox updates to refresh folders. Source themes are never modified.
Use --gruvbox /path/to/theme and --papirus /path/to/theme if detection is ambiguous.
Only output previously created by this script can be replaced. No sudo needed.
"""
import argparse
import configparser
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

MARKER = '.generated-icon-theme.json'
# Keep the original marker identity so existing v1 outputs can be rebuilt.
GENERATOR = 'papirus-gruvbox-builder-v1'
EXTENSIONS = {'.svg', '.png', '.xpm', '.svgz'}
# Explicit aliases only: a generic network/application icon must not become an
# override merely because its symlink happens to point at folder artwork.
SPECIAL = {
    'user-home', 'user-home-open', 'user-desktop', 'inode-directory',
    'gtk-directory', 'gtk-home', 'gnome-fs-directory', 'gnome-fs-home',
    'gnome-home', 'stock_folder', 'stock_home',
}


def config(path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    with path.open(encoding='utf-8-sig') as stream:
        parser.read_file(stream)
    if not parser.has_section('Icon Theme'):
        raise ValueError('Missing [Icon Theme] in ' + str(path))
    return parser


def split(value):
    return [x.strip() for x in value.split(',') if x.strip()]


def roots():
    # Empty XDG variables mean defaults; relative XDG paths are invalid.
    home = os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local/share')
    if not Path(home).is_absolute():
        home = str(Path.home() / '.local/share')
    paths = [Path(home) / 'icons', Path.home() / '.icons']
    system = os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share'
    paths += [Path(x) / 'icons' for x in system.split(':') if Path(x).is_absolute()]
    return list(dict.fromkeys(p.absolute() for p in paths))


def discover(search):
    themes = {}
    for base in search:
        if base.is_dir():
            for path in sorted(base.iterdir()):
                if (path / 'index.theme').is_file():
                    themes.setdefault(path.name, path)
    return themes


def choose(themes, explicit, kind):
    if explicit:
        path = Path(explicit).expanduser().absolute()
        if not (path / 'index.theme').is_file():
            raise ValueError('No index.theme in ' + str(path))
        return path
    # Generated outputs contain both source names in their display name, and
    # must never be mistaken for a source on subsequent runs.
    candidates = {name: path for name, path in themes.items()
                  if not (path / MARKER).exists()}
    exact = ('Papirus-Dark',) if kind == 'papirus' else ('Gruvbox-Plus-Dark', 'Gruvbox-Dark')
    for name in exact:
        if name in candidates:
            return candidates[name]
    matches = []
    for path in candidates.values():
        display = config(path / 'index.theme').get('Icon Theme', 'Name', fallback='')
        label = (path.name + ' ' + display).lower()
        if kind in label and 'dark' in label:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError('Cannot uniquely detect ' + kind + ' dark. Candidates: ' +
                         ', '.join(str(x) for x in matches) +
                         '. Specify --' + kind + ' /path/to/theme')
    return matches[0]


def entries(theme, accept=None):
    """Read declared directories, respecting search priority and valid aliases."""
    path, cfg, locations = theme
    names = split(cfg.get('Icon Theme', 'Directories', fallback=''))
    names += split(cfg.get('Icon Theme', 'ScaledDirectories', fallback=''))
    for directory in dict.fromkeys(names):
        rel = Path(directory)
        if (not rel.parts or rel.is_absolute() or '..' in rel.parts or
                str(rel) != directory or not cfg.has_section(directory)):
            raise ValueError('Invalid directory metadata: ' + str(path) + ': ' + directory)
        meta = dict(cfg[directory])
        for key in ('Size', 'Scale'):
            if int(meta.get(key, '1' if key == 'Scale' else '0')) <= 0:
                raise ValueError('Invalid ' + key + ' for ' + directory + ' in ' + str(path))
        found = set()
        for location in locations:
            source = location / rel
            if not source.is_dir():
                continue
            for icon in sorted(source.iterdir()):
                if icon.suffix.lower() not in EXTENSIONS or icon.name in found:
                    continue
                if accept is not None and not accept(icon, meta):
                    continue
                try:
                    target = icon.resolve(strict=True)
                    if not target.is_file():
                        continue
                except (OSError, RuntimeError):
                    print('Warning: skipping broken/cyclic link ' + str(icon), file=sys.stderr)
                    continue
                # A broken alias in an earlier root must not hide a valid file.
                found.add(icon.name)
                yield directory, meta, icon, target


def folder_icon(icon, meta):
    # Follow the target when copying artwork, but classify by the requested name.
    # Context prevents an application called folder-* from replacing an app icon.
    name = icon.stem
    plain = name[:-9] if name.endswith('-symbolic') else name
    context = meta.get('Context', '').lower()
    if plain in SPECIAL:
        return context in {'places', 'mimetypes'}
    return (plain == 'folder' or plain.startswith('folder-')) and context in {'places', 'actions'}


def validate_destination(destination):
    if destination.name in {'.', '..'} or not re.fullmatch(r'[A-Za-z0-9_.-]+', destination.name):
        raise ValueError('Output theme directory must use ASCII letters, numbers, dots, underscores or hyphens')
    if destination.is_symlink():
        raise ValueError('Refusing symlink output directory')
    if destination.exists():
        marker = destination / MARKER
        try:
            data = json.loads(marker.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict) or data.get('generator') != GENERATOR:
            raise ValueError('Refusing to replace a directory not created by this script')


def build(args):
    search = roots()
    themes = discover(search)
    destination = (Path(args.output).expanduser().absolute() if args.output else
                   search[0] / 'Papirus-Gruvbox-Folders')
    validate_destination(destination)
    # Ignore the existing output for detection, but still validate explicit inputs.
    candidates = {name: path for name, path in themes.items()
                  if path.resolve() != destination.resolve()}
    gruv = choose(candidates, args.gruvbox, 'gruvbox')
    pap = choose(candidates, args.papirus, 'papirus')
    for source in list(candidates.values()) + [gruv, pap]:
        src, dst = source.resolve(), destination.resolve()
        if src == dst or src in dst.parents or dst in src.parents:
            raise ValueError('Output must be separate from every source theme')
    if destination.name in {gruv.name, pap.name}:
        raise ValueError('Output must have a different theme name from its sources')
    # Inherits resolves an installed theme name, not an arbitrary filesystem path.
    visible_pap = themes.get(pap.name)
    if visible_pap is None or visible_pap.resolve() != pap.resolve():
        raise ValueError('Papirus must be installed in an icon search directory and not '
                         'shadowed by another theme of the same name: ' + str(pap))
    pap_cfg = config(pap / 'index.theme')
    gruv_cfg = config(gruv / 'index.theme')
    # Do not flatten parents: KDE must retain its own lookup and fallback rules.
    # Check that the new inheritance edge cannot create a cycle through output.
    seen = set()
    def check_parents(path):
        if path.name in seen:
            return
        seen.add(path.name)
        for parent in split(config(path / 'index.theme').get('Icon Theme', 'Inherits', fallback='')):
            if parent == destination.name:
                raise ValueError('Papirus inheritance would create a cycle through the output theme')
            if parent in themes:
                check_parents(themes[parent])
    check_parents(pap)
    locations = [gruv] + [b / gruv.name for b in search
                         if (b / gruv.name).is_dir() and (b / gruv.name).resolve() != gruv.resolve()]
    donor = list(entries((gruv, gruv_cfg, locations), accept=folder_icon))
    if not donor:
        raise ValueError('No Gruvbox folder icons found in declared Places/Actions/MimeTypes directories')
    print('Gruvbox:', gruv)
    print('Papirus:', pap)
    print('Output: ', destination)
    if args.dry_run:
        print('Dry run: found', len(donor), 'Gruvbox folder files; no changes made.')
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + destination.name + '-', dir=destination.parent))
    try:
        out = configparser.ConfigParser(interpolation=None)
        out.optionxform = str
        # Preserve KDE colour-scheme and size preferences, but not Papirus's
        # translated identity, directory inventory or inheritance declaration.
        excluded = {'Name', 'Comment', 'Inherits', 'Directories', 'ScaledDirectories', 'Hidden', 'Example'}
        out['Icon Theme'] = {key: value for key, value in pap_cfg['Icon Theme'].items()
                             if key.split('[', 1)[0] not in excluded}
        out['Icon Theme'].update({'Name': 'Papirus Dark with Gruvbox folders',
                                 'Comment': 'Generated Gruvbox folder overrides; inherits Papirus',
                                 'Inherits': pap.name, 'Example': 'folder'})
        directories, scaled_directories = [], []
        scaled = set(split(gruv_cfg.get('Icon Theme', 'ScaledDirectories', fallback='')))
        for directory, meta, icon, target in donor:
            subdir = 'folders/' + directory
            if subdir not in out:
                out[subdir] = meta
                (scaled_directories if directory in scaled else directories).append(subdir)
            dest = staging / subdir / icon.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target, dest)
            sidecar = icon.with_suffix('.icon')
            if sidecar.is_file():
                shutil.copyfile(sidecar, dest.with_suffix('.icon'))
        out['Icon Theme']['Directories'] = ','.join(directories)
        if scaled_directories:
            out['Icon Theme']['ScaledDirectories'] = ','.join(scaled_directories)
        with (staging / 'index.theme').open('w', encoding='utf-8') as stream:
            out.write(stream, space_around_delimiters=False)
        (staging / MARKER).write_text(json.dumps({'generator': GENERATOR, 'format_version': 2,
            'gruvbox': str(gruv), 'papirus': str(pap), 'overlay': True,
            'counts': {'folders': len(donor), 'linked': 0}}, indent=2) + '\n', encoding='utf-8')
        backup = None
        if destination.exists():
            backup = Path(tempfile.mkdtemp(prefix='.' + destination.name + '-backup-', dir=destination.parent))
            backup.rmdir()
            destination.rename(backup)
        try:
            staging.rename(destination)
        except BaseException:
            if backup:
                backup.rename(destination)
            raise
        if backup:
            shutil.rmtree(backup)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print('Installed:', len(donor), 'folder files; other icons inherit from', pap.name + '.')
    print('Select "Papirus Dark with Gruvbox folders" in System Settings > Icons.')
    print('Restart apps or log out and back in if they retain old icons.')
    print('Rerun after Gruvbox updates to refresh folders. Papirus updates are inherited automatically.')
    if destination.parent not in search:
        print('Warning: output is outside the icon search directories; install it before selecting it.', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--gruvbox', help='Gruvbox Dark theme directory')
    parser.add_argument('--papirus', help='Installed Papirus Dark theme directory')
    parser.add_argument('--output', help='Destination theme directory')
    parser.add_argument('--overlay', action='store_true', help='Compatibility option: folder-only overlay is now always used')
    parser.add_argument('--dry-run', action='store_true', help='Validate themes and folders without writing anything')
    args = parser.parse_args()
    try:
        build(args)
    except (OSError, ValueError, configparser.Error, RuntimeError) as exc:
        parser.exit(1, 'Error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
