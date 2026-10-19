#!/usr/bin/env python3
"""Build Papirus Dark with Gruvbox Dark folders; Python 3.8+, no dependencies.

Run: python3 build_icon_theme.py
Then select 'Papirus Dark with Gruvbox folders' in KDE's icon settings.
Rerun after theme updates to discover added/removed icons and refresh folders.
Existing Papirus files update through symlinks. Source themes are never modified.
Use --overlay for a smaller folder-only theme with Inherits=Papirus-Dark.
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
GENERATOR = 'papirus-gruvbox-builder-v1'
EXTENSIONS = {'.svg', '.png', '.xpm', '.svgz'}
SPECIAL = {'user-home', 'user-desktop', 'inode-directory'}


def config(path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    with path.open(encoding='utf-8-sig') as stream:
        parser.read_file(stream)
    return parser


def split(value):
    return [x.strip() for x in value.split(',') if x.strip()]


def roots():
    paths = [Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'icons',
             Path.home() / '.icons']
    paths += [Path(x) / 'icons' for x in os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if x]
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
        themes[path.name] = path
        return path
    exact = 'Papirus-Dark' if kind == 'papirus' else 'Gruvbox-Dark'
    if exact in themes:
        return themes[exact]
    candidates = []
    for path in themes.values():
        display = config(path / 'index.theme').get('Icon Theme', 'Name', fallback='')
        label = (path.name + ' ' + display).lower()
        if kind in label and 'dark' in label:
            candidates.append(path)
    if len(candidates) != 1:
        raise ValueError('Cannot uniquely detect ' + kind + ' dark. Candidates: ' +
                         ', '.join(str(x) for x in candidates) +
                         '. Specify --' + kind + ' /path/to/theme')
    return candidates[0]


def chain(start, themes, search):
    """Depth-first theme inheritance, with cycle protection and hicolor last."""
    result, seen = [], set()
    def visit(path):
        if path.name in seen:
            return
        seen.add(path.name)
        cfg = config(path / 'index.theme')
        locations = [path] + [base / path.name for base in search
                             if (base / path.name).is_dir() and base / path.name != path]
        result.append((path, cfg, locations))
        for parent in split(cfg.get('Icon Theme', 'Inherits', fallback='')):
            if parent == 'hicolor':
                continue
            if parent in themes:
                visit(themes[parent])
            else:
                print('Warning: missing inherited theme ' + parent, file=sys.stderr)
    visit(start)
    if 'hicolor' in themes and start.name != 'hicolor':
        visit(themes['hicolor'])
    return result


def entries(theme):
    """Read declared directories, including symlinked directories and aliases.

    Unlisted directories are ignored, as they are by theme loaders. Inventing
    size metadata for those directories would change theme semantics.
    """
    path, cfg, locations = theme
    names = split(cfg.get('Icon Theme', 'Directories', fallback=''))
    names += split(cfg.get('Icon Theme', 'ScaledDirectories', fallback=''))
    for directory in dict.fromkeys(names):
        rel = Path(directory)
        if rel.is_absolute() or '..' in rel.parts or not cfg.has_section(directory):
            raise ValueError('Invalid directory metadata: ' + str(path) + ': ' + directory)
        meta = dict(cfg[directory])
        if 'Size' not in meta:
            raise ValueError('Missing Size for ' + directory + ' in ' + str(path))
        found = set()
        for location in locations:
            source = location / rel
            if not source.is_dir():
                continue
            for icon in sorted(source.iterdir()):
                if icon.suffix.lower() not in EXTENSIONS or icon.name in found:
                    continue
                found.add(icon.name)
                try:
                    target = icon.resolve(strict=True)
                    if not target.is_file():
                        continue
                except (OSError, RuntimeError):
                    print('Warning: skipping broken/cyclic link ' + str(icon), file=sys.stderr)
                    continue
                yield directory, meta, icon, target


def folder_icon(icon, target, meta):
    # Follow aliases such as inode-directory -> folder.svg and folder symlinks
    # which point into a colour-specific directory outside the declared tree.
    names = {icon.stem, target.stem}
    return any(name == 'folder' or name.startswith('folder-') or
               name in SPECIAL for name in names)


def build(args):
    search = roots()
    themes = discover(search)
    gruv = choose(themes, args.gruvbox, 'gruvbox')
    pap = choose(themes, args.papirus, 'papirus')
    destination = (Path(args.output).expanduser().absolute() if args.output else
                   search[0] / 'Papirus-Gruvbox-Folders')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', destination.name):
        raise ValueError('Output theme directory must use ASCII letters, numbers, dots, underscores or hyphens')
    for source in list(themes.values()):
        src, dst = source.resolve(), destination.resolve()
        if src == dst or src in dst.parents or dst in src.parents:
            raise ValueError('Output must be separate from every source theme')
    if destination.is_symlink():
        raise ValueError('Refusing symlink output directory')
    if destination.exists():
        marker = destination / MARKER
        if not marker.is_file() or json.loads(marker.read_text()).get('generator') != GENERATOR:
            raise ValueError('Refusing to replace a directory not created by this script')
    # Gruvbox is intentionally read directly: missing Gruvbox folder variants
    # should come from Papirus rather than an unrelated Gruvbox parent theme.
    donor = list(entries((gruv, config(gruv / 'index.theme'),
                          [gruv] + [b / gruv.name for b in search if (b / gruv.name).is_dir() and b / gruv.name != gruv])))
    donor = [item for item in donor if folder_icon(item[2], item[3], item[1])]
    if not donor:
        raise ValueError('No Gruvbox folder icons found in declared directories')
    override_names = {item[2].stem for item in donor}
    layers = [] if args.overlay else chain(pap, themes, search)
    print('Gruvbox:', gruv)
    print('Papirus:', pap)
    print('Output: ', destination)
    if args.dry_run:
        print('Dry run: found', len(donor), 'Gruvbox folder files; no changes made.')
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + destination.name + '-', dir=destination.parent))
    counts = {'folders': 0, 'linked': 0}
    try:
        out = configparser.ConfigParser(interpolation=None)
        out.optionxform = str
        out['Icon Theme'] = {'Name': 'Papirus Dark with Gruvbox folders',
                             'Comment': 'Generated Gruvbox folders and live Papirus icons',
                             'Inherits': pap.name if args.overlay else 'hicolor'}
        directories = []
        def emit(prefix, item, copy):
            directory, meta, icon, target = item
            subdir = prefix + '/' + directory
            if subdir not in out:
                out[subdir] = meta
                directories.append(subdir)
            dest = staging / subdir / icon.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if copy:
                shutil.copyfile(target, dest)
            else:
                # Link the original alias path, not its current resolved target:
                # upstream updates can retarget that alias without a rebuild.
                dest.symlink_to(icon.absolute())
            sidecar = icon.with_suffix('.icon')
            if sidecar.is_file():
                shutil.copyfile(sidecar, dest.with_suffix('.icon'))
        for item in donor:
            emit('folders', item, True)
            counts['folders'] += 1
        claimed = set(override_names)
        for number, layer in enumerate(layers):
            items = list(entries(layer))
            # Inheritance selects an icon name from the first theme containing
            # it, regardless of size. Preserve that when flattening the tree.
            accepted = [item for item in items if item[2].stem not in claimed]
            for item in accepted:
                emit('base-' + str(number), item, False)
                counts['linked'] += 1
            claimed.update(item[2].stem for item in items)
        out['Icon Theme']['Directories'] = ','.join(directories)
        with (staging / 'index.theme').open('w', encoding='utf-8') as stream:
            out.write(stream, space_around_delimiters=False)
        (staging / MARKER).write_text(json.dumps({'generator': GENERATOR,
            'gruvbox': str(gruv), 'papirus': str(pap), 'overlay': args.overlay,
            'counts': counts}, indent=2) + '\n')
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
    print('Installed:', counts['folders'], 'folder files;', counts['linked'], 'linked base files.')
    print('Select "Papirus Dark with Gruvbox folders" in System Settings > Icons.')
    print('Restart apps if needed. Rerun this script after theme updates to refresh the inventory.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--gruvbox', help='Gruvbox Dark theme directory')
    parser.add_argument('--papirus', help='Papirus Dark theme directory')
    parser.add_argument('--output', help='Destination theme directory')
    parser.add_argument('--overlay', action='store_true', help='Copy folders only; inherit all other icons from Papirus Dark')
    parser.add_argument('--dry-run', action='store_true', help='Detect themes and folders without writing anything')
    args = parser.parse_args()
    try:
        build(args)
    except (OSError, ValueError, configparser.Error, RuntimeError) as exc:
        parser.exit(1, 'Error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
