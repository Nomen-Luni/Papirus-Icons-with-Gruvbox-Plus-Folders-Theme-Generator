A Python script that combines Gruvbox Dark folder icons with Papirus Dark's remaining icons. Note **This software was generated using ChatGPT.** I have cast an eye over the code but don't claim to have done a deep review. As with all free software - use at your own risk.

## Usage

Install both icon themes and Python 3, then run without sudo:

```bash
python3 build_icon_theme.py
```

Select **Papirus Dark with Gruvbox folders** in KDE's icon settings.

The default build copies Gruvbox folders and links to installed Papirus icons. Existing Papirus icons update through those links; rerun the script after theme updates to pick up additions/removals and refresh the folders.

Use `--overlay` for a folder-only theme that inherits Papirus Dark instead. Use `--dry-run` to check theme detection without writing files, or `--help` for custom source and output paths. Neither original theme is modified.

## Acknowledgements

- **Papirus Dark:** the [Papirus Development Team and contributors](https://github.com/PapirusDevelopmentTeam/papirus-icon-theme), whose theme builds on the [Paper Icon Set](https://github.com/snwh/paper-icon-theme).
- **Gruvbox Plus folder artwork:** [SylEleuth](https://github.com/SylEleuth/gruvbox-plus-icon-pack).
- **Original Gruvbox colour scheme:** [morhetz (Pavel Pertsev)](https://github.com/morhetz/gruvbox).

All credit for the original icon artwork belongs to its respective creators. The artwork remains subject to its original licences; this script does not change theme.

The generated icon set is covered by the GPL-3.0 licence in accordance with the licencing of the icon sets from which it is derived.
