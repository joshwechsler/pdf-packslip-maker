# Pack Slip Maker

A standalone macOS app that turns the weekly order spreadsheet (.xlsx) into one
print-ready PDF, one branded pack slip per customer. It runs fully offline, with no
Python, terminal, or subscriptions needed on the Operator's Mac.

- **Operator instructions (one page):** [`docs/OPERATOR_GUIDE.md`](docs/OPERATOR_GUIDE.md).
  The build turns this into `How to use Pack Slip Maker.pdf` inside the download zip.
- **Download the app:** GitHub → **Actions** → *Build macOS app* → latest run →
  **Artifacts → Pack-Slip-Maker-mac**. Pushing a tag like `v1.0.0` also attaches the
  zip to a GitHub Release.

## How it works

| Stage | Module | SRS |
| --- | --- | --- |
| Load `.xlsx` (drag-and-drop, Dock drop, or Browse) | `packslip/spreadsheet.py`, `app.py` | FR-1, FR-9 |
| Match columns → pack-slip fields, saved and reused | `mapping.py`, `mapping_dialog.py` | FR-2, FR-3 |
| Layout designer: drag, resize, style, live preview | `designer.py`, `layout.py` | FR-4, FR-6 |
| Named layout templates (JSON), logo, brand colors | `template.py` | FR-5, FR-10 |
| One combined PDF, one page per row | `pdfgen.py` | FR-7, FR-8, NFR-5 |

The designer preview and the PDF use the same text-fitting code (reportlab font
metrics), so lines wrap in the same places on screen and on paper. Long values shrink
to fit their box, then truncate with "...".

**Designer extras:** text items accept `{Field Name}` placeholders (for example
`{City}, {State} {Zip}`), and field items can split a cell into one line per item
(at newlines, commas, or semicolons) with optional bullets. Page sizes: Letter,
Half Letter, A4, and 4×6 label.

### Where data lives

Everything stays on the Operator's Mac (NFR-7):

```
~/Library/Application Support/Pack Slip Maker/
    mapping.json        column matches (FR-3)
    templates/*.json    layouts (FR-5)
    assets/             copied logo files
    settings.json       last folder / selected layout
    error-log.txt       only written if something unexpected happens
```

PDFs are saved next to the spreadsheet as
`Pack Slips - <spreadsheet name> - <YYYY-MM-DD>.pdf`. Existing files are never
overwritten. If that folder is read-only, PDFs go to `~/Documents/Pack Slips`.

## Developing

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python main.py                      # run the app
.venv/bin/python -m pytest -q                 # unit tests
.venv/bin/python tools/make_sample.py         # regenerate sample/sample_orders.xlsx
.venv/bin/python main.py --generate sample/sample_orders.xlsx --out /tmp/test.pdf
.venv/bin/python main.py --selftest           # 300-row end-to-end check
```

## Building the .app

CI (`.github/workflows/build-macos.yml`) builds on every push. To build locally on a Mac:

1. Install Python 3.12 from **python.org** (its "universal2" build is needed for an
   Intel + Apple Silicon app; Homebrew Python is single-architecture).
2. Run these commands:
   ```bash
   /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 -m venv venv && source venv/bin/activate
   pip install delocate pyinstaller==6.16.0
   python packaging/install_universal2_deps.py requirements.txt   # fuses arm64 + x86_64 wheels
   pyinstaller --noconfirm packaging/PackSlipMaker.spec
   codesign --force --deep --sign - "dist/Pack Slip Maker.app"     # ad-hoc signature
   ```

`packaging/hooks/hook-tkinterdnd2.py` replaces the stock hook so both the Intel and
Apple Silicon drag-and-drop libraries are bundled.

## Differences from the SRS

- **Config location:** files live in `~/Library/Application Support`, not "alongside the
  app". macOS app bundles are read-only once installed, and Gatekeeper may run unsigned
  apps from a randomized read-only path.
- **No pandas:** spreadsheets are read with openpyxl alone. pandas and numpy would add
  about 60 MB and complicate the universal2 build without adding anything this app needs.
- **Gatekeeper on macOS 15 (Sequoia) and later:** right-click → Open no longer bypasses
  the warning. The Operator uses **System Settings → Privacy & Security → Open Anyway**
  once. The Operator guide covers both paths.
- **Fonts:** the built-in PDF fonts are Helvetica, Times, and Courier, so the app needs
  no font files. Characters outside Western European (such as emoji or CJK) print as `?`.

## Open items (SRS §8)

Placeholders are in place, and each item can be swapped in without code changes:

| Item | Placeholder now | Where to change |
| --- | --- | --- |
| Real spreadsheet headers | `sample/sample_orders.xlsx` (fake data) | Remap Fields in the app; aliases in `mapping.py` `DEFAULT_FIELDS` |
| Logo + brand colors | Empty logo box, navy `#1F3A5F` / gold `#C8A24A` | Edit Layout → Logo / Brand; defaults in `template.py` |
| Initial field list | Customer, Order #, Delivery Date, Address, Phone, Items, Qty, Notes | `mapping.py` `DEFAULT_FIELDS`, `template.py` `default_template()` |
