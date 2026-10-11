# VisionMate shipped source

The source snapshot in `addon/` is from the publicly available VisionMate 0.3.1 package. The Python files now carry GPL v2 or later notices. This does not change or replace the existing 0.3.1 download. No private development history is included.

## License

VisionMate's Python add-on code is licensed under the GNU General Public License, version 2 or later. See `LICENSE`. The bundled engine and its dependencies retain their own licenses. The separately downloaded vision data retains its own license.

## Prepare a package

1. Download the existing 0.3.1 `.nvda-addon` from this repository's release page and open it as a ZIP archive. This is the verified source of the prebuilt engine binaries for this snapshot.
2. Copy its `engine/` folder, including the engine license files, into `addon/`. The engine binaries are not duplicated in this source snapshot.
3. Include `LICENSE` and the VisionMate GPL notice in the package root.
4. Update `addon/manifest.ini` to a new version before distributing any changed package. Do not replace an existing version's download with different bytes.
5. ZIP the contents of `addon/`, not the containing directory, and use the `.nvda-addon` extension. `manifest.ini`, `globalPlugins/`, `engine/` and `doc/` must be at the ZIP root.
6. Test on Windows with NVDA before publishing. The declared NVDA versions in the manifest are not a substitute for testing.

The existing `datainfo.json` identifies the separately hosted vision-data pack and its checksum. The model is downloaded on first use, not embedded in the add-on package. This snapshot documents assembly using the existing released engine. It does not claim a reproducible engine build.
