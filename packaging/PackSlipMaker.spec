# PyInstaller spec: builds "Pack Slip Maker.app" as a universal2 (Intel + Apple Silicon) bundle.
# Run on macOS:  pyinstaller --noconfirm packaging/PackSlipMaker.spec
import os
import sys

ROOT = os.path.dirname(SPECPATH)
sys.path.insert(0, ROOT)
from packslip import APP_NAME, __version__  # noqa: E402

TARGET_ARCH = os.environ.get("PACKSLIP_TARGET_ARCH", "universal2") or None

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    hookspath=[os.path.join(SPECPATH, "hooks")],
    hiddenimports=["PIL._tkinter_finder", "PIL.ImageTk"],
    excludes=["pandas", "numpy", "matplotlib", "IPython", "pytest", "pypdf", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)
app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=os.path.join(SPECPATH, "icon.png"),
    bundle_identifier="com.packslipmaker.app",
    version=__version__,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        # The UI is designed for light mode; keep it consistent in dark mode.
        "NSRequiresAquaSystemAppearance": True,
        # Lets the Operator drop a spreadsheet on the Dock icon / use "Open With".
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "Excel Workbook",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["org.openxmlformats.spreadsheetml.sheet"],
            "CFBundleTypeExtensions": ["xlsx", "xlsm"],
        }],
    },
)
