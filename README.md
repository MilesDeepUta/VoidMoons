# MoonScan

Desktop tool for tracking EVE Online moon scans against an alliance assignment.

Paste scan data from the in-game survey window, watch the constellation map fill
in as you go, and export your progress in the exact format the alliance expects.

## What it does

- Pick a region → constellation → systems during first-run setup. Those become
  your "assignment" — the moons that count toward your goal.
- Paste scan data from the EVE moon-scanner's "Copy to Clipboard" button (manual
  or auto-watched). Every scan is stored verbatim.
- Drill down through three views: constellation map → system planets → moons
  with ore breakdowns.
- Export your progress back to the clipboard as a single block of paste-ready
  text, byte-identical to what you'd get if you'd scanned everything in one go
  in EVE.
- Scans of moons outside your assignment are kept (as "stranger moons") but
  don't count toward your progress.

## Byte-exact export

The most important guarantee: **the exported paste is byte-for-byte identical
to a real in-game paste**. When you ingest your first real scan, the app
captures the format bytes (header line, line endings, trailer) from that
clipboard read. Every moon's bytes are stored as a BLOB in SQLite without
re-encoding. On export, the app concatenates the original header + each
moon's stored bytes + the original trailer. Tests (`tests/test_parser.py`,
`tests/test_ingest.py`) pin this guarantee for CRLF, LF, and trailing-newline
variants.

## Running from source

```
python -m venv .venv
.venv\Scripts\activate           # Windows
# or: source .venv/bin/activate  # macOS / Linux

pip install -r requirements.txt
python -m moonscan
```

First launch will pop the setup wizard. After that, your assignment is saved
and the app opens straight to the constellation map.

## Running the tests

```
PYTHONPATH=. pytest tests/
```

16 tests in total. The critical ones are
`tests/test_parser.py::test_round_trip_byte_exact[*]` and
`tests/test_ingest.py::test_full_ingest_then_export_round_trip` — these are
the byte-identical-export guarantees.

## Building a standalone .exe

```
pip install pyinstaller
python build_exe.py
```

The output lands in `dist/MoonScan/`. Zip that folder and ship it. End-users
double-click `MoonScan.exe` inside the unzipped folder.

The spec uses `--onedir` (not `--onefile`) on purpose: single-exe PyInstaller
builds frequently trip Windows Defender heuristics, which would be a problem
for alliance distribution. The trade-off is a folder of files instead of one
exe — minor inconvenience, much fewer false positives.

User data (`user.db`, settings) lives in:
- Windows: `%APPDATA%\MoonScan\`
- macOS:   `~/Library/Application Support/MoonScan/`
- Linux:   `~/.local/share/moonscan/`

Set the `MOONSCAN_DATA_DIR` environment variable to override (useful for
portable mode on a USB stick).

## Rebuilding the EVE static data

`data/eve_static.db` (29.8 MB) is built from the EVE Static Data Export. It
ships with the app and rarely needs rebuilding — moon IDs don't change. If
CCP publishes a new SDE and you want to refresh:

```
python build_sde.py --src /path/to/sde/jsonl --out data/eve_static.db
```

The source directory must contain these jsonl files: `mapRegions`,
`mapConstellations`, `mapSolarSystems`, `mapPlanets`, `mapMoons`,
`mapStargates`.

## Project layout

```
moonscan_project/
├── build_sde.py              # SDE → eve_static.db preprocessor
├── build_exe.py              # PyInstaller wrapper
├── moonscan.spec             # PyInstaller spec
├── requirements.txt
├── data/
│   └── eve_static.db         # Shipped with the app (read-only)
├── moonscan/
│   ├── __init__.py
│   ├── __main__.py           # `python -m moonscan` entry point
│   ├── app.py                # QApplication setup, first-run wizard trigger
│   ├── paths.py              # Cross-platform user-data dir resolution
│   ├── db.py                 # user.db SQLite wrapper
│   ├── static_db.py          # eve_static.db read-only reader
│   ├── parser.py             # Byte-exact scan paste parser
│   ├── export.py             # Reassembles raw chunks for the alliance
│   ├── clipboard.py          # Qt clipboard read + polling watcher
│   ├── ingest.py             # parser → DB pipeline
│   ├── theme.py              # Dark Fusion palette + status colors
│   └── ui/
│       ├── main_window.py    # Toolbar, breadcrumbs, drill-down stack
│       ├── setup_wizard.py   # First-run region/constellation/systems picker
│       ├── views/
│       │   ├── map_view.py   # L1: graphical constellation map
│       │   ├── system_view.py# L2: planets in a system
│       │   └── moon_list.py  # L3: moons + ore breakdowns
│       └── dialogs/
│           ├── paste_dialog.py     # Manual paste preview/save
│           ├── export_dialog.py    # Built export with copy-to-clipboard
│           └── settings_dialog.py  # Backup, restore, edit assignment, watcher
└── tests/
    ├── test_parser.py        # Parser + round-trip byte-exact tests
    ├── test_ingest.py        # End-to-end DB integration tests
    └── fixtures/
        ├── sample_paste_no_trailing.bin
        ├── sample_paste_with_trailing.bin
        └── sample_paste_lf.bin
```

## How rescans work

Each moon has exactly one row in the `scans` table, keyed by `moon_id`. When
you paste an updated scan, the row is overwritten in place with the new bytes
and ore breakdown. You never end up with stale data, and the export always
reflects the most recent scan of each moon.

## Notes on the clipboard watcher

When enabled, the watcher polls the system clipboard every 500 ms (configurable
in Settings). When it sees content that looks like a moon scan paste, it opens
the paste dialog pre-populated with that content — it never auto-saves, so it
won't eat unrelated clipboard copies. Toggle it from the toolbar.
