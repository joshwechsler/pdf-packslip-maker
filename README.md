# Packs Be Slippin'

A standalone macOS app that turns the weekly order spreadsheet (.xlsx) into one
print-ready PDF, one branded pack slip per customer. It runs fully offline, with no
Python, terminal, or subscriptions needed on the Operator's Mac.

- **Operator instructions (one page):** [`docs/OPERATOR_GUIDE.md`](docs/OPERATOR_GUIDE.md).
  The build turns this into `How to use Packs Be Slippin'.pdf` inside the download zip.
- **Download the app:** [latest release](https://github.com/joshwechsler/pdf-packslip-maker/releases/latest)
  → `Packs-Be-Slippin-mac.zip`. Installed apps update themselves (see *Updates* below).

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

**Designer extras:** an **Item List** element (tick box, quantity, dish name), text items accept `{Field Name}` placeholders (for example
`{City}, {State} {Zip}`), and field items can split a cell into one line per item
(at newlines, commas, or semicolons) with optional bullets. Page sizes: Letter,
Half Letter, A4, and 4×6 label.

### Where data lives

Everything stays on the Operator's Mac (NFR-7):

```
~/Library/Application Support/Packs Be Slippin'/
    mappings/*.json     column matches, one file per layout (FR-3)
    templates/*.json    layouts (FR-5)
    assets/             copied logo files
    settings.json       last folder / selected layout
    error-log.txt       only written if something unexpected happens
    diagnostics.txt     breadcrumbs (screens/actions, no customer data) + stack dump if the UI hangs >10s
```

PDFs are saved next to the spreadsheet as
`Pack Slips - <spreadsheet name> - delivery <YYYY-MM-DD>.pdf`. Existing files are never
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
   codesign --force --deep --sign - "dist/Packs Be Slippin'.app"     # ad-hoc signature
   ```

`packaging/hooks/hook-tkinterdnd2.py` replaces the stock hook so both the Intel and
Apple Silicon drag-and-drop libraries are bundled.

## Updates (in-app)

Every successful build of `claude/packslip-app` or `main` publishes a GitHub Release tagged
`build-<run number>` with the zip attached. CI stamps the number into `packslip/_build.py`.

- On launch (and via **Check for Updates**), the Mac app asks
  `api.github.com/repos/joshwechsler/pdf-packslip-maker/releases/latest`. If that build is
  newer, it offers **Update Now**. Offline, nothing happens.
- Install steps (`packslip/updater.py`):
  1. Download with `/usr/bin/curl`, so there's no quarantine flag and no second Gatekeeper prompt.
  2. Check the release's SHA-256.
  3. Unzip with `ditto`.
  4. Run `codesign --verify` on the new app.
  5. A small script waits for the app to quit, swaps the bundle (restoring the old one on
     failure) and reopens it.
- Only the version check goes to GitHub. No spreadsheet or customer data is sent.
- If macOS runs the app from a translocated path (not moved into Applications), or the
  folder isn't writable, the app explains what to do instead.
- CI runs `--selftest-update` on macOS against the freshly built zip before publishing.

The first build with the updater has to be installed by hand once.

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

## Several businesses

Column matches are stored **per layout** (`mappings/<layout>.json`), so each business gets a
layout with its own columns, logo, brand colors and remembered delivery weekday.

- On loading a spreadsheet, the app keeps the selected layout if its matches fit. Otherwise it
  switches to the layout that fits best (`Mapping.fit_score`).
- If nothing fits, it asks: "different business → new layout" or "headings changed → re-match".
- In Edit Layout, **Duplicate** copies a layout *with* its matches (a variation for the same
  business). **New** starts with no matches and no logo (a different business).
- The old app-wide `mapping.json` is copied to every existing layout on first launch.

## One row per item (store exports)

Fulfillment exports list **one row per item**, with the customer details repeated on each row
(e.g. `Order, Customer, …, Product, Variant, Quantity, Modifiers, …, Full Address, Customer Phone,
Driver Instructions, Delivery Zone, Delivery Window`). In this "rows" mode:

- Rows with the same **Order** value become one pack slip. Customer details come from the
  order's first row. The mode is detected automatically when a column repeats on neighbouring rows.
- Each item shows its quantity and name, plus its **Variant** unless it's Default/Regular/Standard
  (so "Small" stands out). **Modifiers** print smaller underneath (custom-meal components;
  "(1x)" is dropped).
- **Delivery / Pickup**, **Pickup Location** (blanked on delivery orders, where it's the
  kitchen), **Delivery Window** and **Route / Zone** are available, and the default layout
  shows them top-right.
- `.csv` files are read directly (UTF-8 or Windows encoding; leading zeros in ZIP codes kept).
- If the file has a single **Fulfillment/Delivery Date**, the date picker pre-selects it.

## Whole order in one cell

Some exports put each customer's whole order in a single **Items** cell:

`Custom Chicken (2x Default); Modifiers: Grilled Chicken Breast 4oz (1x); Broccoli 1 cup (1x); Teriyaki Steak Tips (1x Regular); $10 delivery (1x Default);`

`parse_item_list` (in `mapping.py`) splits this at semicolons:
- `Name (Nx Size)` starts an item.
- Parts after `Modifiers:` (written `(Nx)`) attach to the item before them.
- Sizes show unless Regular/Default/Standard.
- Lines starting with `$` (fees) are skipped.

This applies automatically when the item column is in that format. A plain list still works.

## Real spreadsheet format

The weekly Google Sheet (downloaded as .xlsx) has **one row per customer** and **one column per
menu item** with the quantity in the cell, then a `TOTALS` row:

`Order Received | Customer Name | Phone Number | Address | <dish> … <dish> | Delivery Fee | Total Cost | Paid | Delivery Instructions`

- Menu items are "every column after **Address** and before **Delivery Fee**". The rule is
  stored by those two anchor headings, not by dish names, so a new menu each week needs no
  remapping. Both anchors can be changed on the mapping screen.
- Only dishes with a quantity above 0 print. The **Item List** layout element shows a tick box,
  the quantity and the dish name, and `{Total Items}` gives the sum of quantities.
- Rows whose cell reads `TOTAL`, `TOTALS`, `Grand Total` or `Subtotal` are skipped.
- 10-digit phone numbers print as `(203) 555-0147`.
- **Delivery date** isn't in the sheet. The Operator picks it in the app (dropdown of the next 4
  weeks plus a calendar, defaulting to the next occurrence of the last-used weekday). It prints as
  `{Delivery Date}` / the "Delivery Date" field, and in the PDF filename.
- Sheets with all items in one column are still supported ("All items are listed in one column").

`sample/sample_orders.xlsx` is fake data in this exact shape.

## Open items (SRS §8)

| Item | Status |
| --- | --- |
| Real spreadsheet headers | ✅ Received. Default fields and layout are built around them |
| Logo + brand colors | ✅ Logo: black "MEAL + PREP" wordmark (`packslip/assets/meal_prep_logo.png`, redraw with `tools/make_logo.py`), installed as the default on first run. Brand colors: black `#000000` / dark gray `#555555` to match (Edit Layout → Brand, no rebuild) |
| Field list for the slip | ✅ Name, address, phone, order date, items with tick boxes, total items, delivery instructions. Total Cost and Paid are matched but deliberately left off the slip |
