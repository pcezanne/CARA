# Troubleshooting

## Qt platform-plugin error: "Could not find the Qt platform plugin 'cocoa'"

This error almost always has one of two causes — neither is an actual missing file, broken signature, or corrupt install, despite what it looks like.

### Cause 1: PyQt6 / PyQt6-Qt6 version mismatch

`requirements.txt` pins both `PyQt6` and `PyQt6-Qt6` to the same exact version. They must match. A plain `pip install -r requirements.txt` on a clean venv should not produce drift, but manual upgrades of one package can.

Diagnose:

```bash
pip show PyQt6 PyQt6-Qt6 | grep -E "Name|Version"
```

If the versions don't match, reinstall whichever one is ahead to match the other:

```bash
pip install --force-reinstall --no-deps PyQt6-Qt6==<matching version>
```

PyPI doesn't always have every point-release pair available for both packages — run `pip install PyQt6-Qt6==` (no version, to list what's available) if the exact match isn't found.

### Cause 2: macOS UF_HIDDEN flag on installed dylibs

PyQt6-Qt6, installed via pip, carries a `com.apple.provenance` extended attribute; on macOS this causes the OS to assert `UF_HIDDEN` on the installed dylibs, including `libqcocoa.dylib` and its sibling platform plugins. The flag is invisible to permissions, dlopen, and codesigning checks but prevents Qt plugin discovery.

CARA clears this flag automatically at every startup (`app/utils/macos_startup.py` → `clear_platform_plugin_hidden_flags()` called in `cara.py` before `QApplication` is constructed). This is why you must run `cara.py` rather than a raw Python script if you hit this issue.

If you still hit the error after startup has run (e.g., running Python directly without going through `cara.py`), clear manually:

```bash
python3 -c "
import os, glob
plugins = glob.glob(os.path.expanduser('~/.venv/lib/python*/site-packages/PyQt6/Qt6/plugins/platforms/*.dylib'))
for p in plugins:
    st = os.lstat(p)
    if hasattr(st, 'st_flags') and st.st_flags & 0x8000:
        os.chflags(p, st.st_flags & ~0x8000)
        print('cleared', p)
"
```

(Adjust the venv path to match yours.)
