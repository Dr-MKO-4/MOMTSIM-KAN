# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — MoMTSim backend server.
Produit un dossier dist/momtsim_server/ (--onedir) embarqué par Electron.

Construire avec :
    pyinstaller momtsim.spec --clean --noconfirm
"""

block_cipher = None

# ── Fichiers de données à embarquer ──────────────────────────────────────────
extra_datas = [
    ("paramFiles",                 "paramFiles"),
    ("fraudScenariosConfig.json",  "."),
    ("frontend/dist",              "frontend/dist"),
]

# ── Imports cachés — uvicorn + FastAPI + starlette staticfiles ────────────────
hidden = [
    # uvicorn internals
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # FastAPI / Starlette
    "starlette.staticfiles",
    "starlette.responses",
    "starlette.templating",
    # async deps
    "aiofiles",
    "aiofiles.os",
    "aiofiles.threadpool",
    "anyio",
    "anyio._backends._asyncio",
    # http parsing
    "h11",
    "h11._readers",
    "h11._writers",
    # pydantic v2
    "pydantic.deprecated.config",
    "pydantic_core",
    # click (used internally by uvicorn CLI)
    "click",
    # backend package
    "backend",
    "backend.api",
    "backend.pipeline_runner",
    "backend.schemas",
    "backend.config_manager",
    "backend.run_registry",
]

a = Analysis(
    ["run_server.py"],
    pathex=["."],
    binaries=[],
    datas=extra_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # exclure les librairies inutiles pour réduire la taille
    excludes=["tkinter", "PIL", "cv2", "sklearn", "matplotlib", "IPython", "jupyter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="momtsim_server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=True : pas de fenêtre CMD visible car Electron spawne avec windowsHide
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="momtsim_server",
)
