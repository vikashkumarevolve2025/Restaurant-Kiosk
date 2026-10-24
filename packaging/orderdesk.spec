# PyInstaller recipe: turns orderdesk.py and the app into a folder with OrderDesk.exe (no Python needed on the customer's PC).
# Build from the project folder:  pyinstaller packaging/orderdesk.spec --noconfirm --distpath dist --workpath build
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [(os.path.join(ROOT, "static"), "static")]
datas += collect_data_files("escpos")      # printer capability tables
datas += collect_data_files("tzdata")      # time zones (Windows has none of its own)

hidden = collect_submodules("uvicorn") + collect_submodules("escpos") + ["win32print", "h11", "anyio._backends._asyncio"]

a = Analysis(
    [os.path.join(ROOT, "orderdesk.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "httpx"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="OrderDesk", debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="OrderDesk")
