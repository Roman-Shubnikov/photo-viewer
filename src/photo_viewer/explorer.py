import ctypes
from ctypes import POINTER, byref, c_uint, c_ulong, c_void_p, c_wchar_p
from pathlib import Path

_shell32 = ctypes.WinDLL("shell32")
_ole32 = ctypes.WinDLL("ole32")

_shell32.SHParseDisplayName.argtypes = [c_wchar_p, c_void_p, POINTER(c_void_p), c_ulong, POINTER(c_ulong)]
_shell32.SHParseDisplayName.restype = ctypes.HRESULT
_shell32.SHOpenFolderAndSelectItems.argtypes = [c_void_p, c_uint, c_void_p, c_ulong]
_shell32.SHOpenFolderAndSelectItems.restype = ctypes.HRESULT
_ole32.CoTaskMemFree.argtypes = [c_void_p]


def reveal_in_explorer(path: Path) -> None:
    """Opens the containing folder in Windows Explorer with the file selected.

    Uses the shell call Explorer itself relies on, so the window comes to the front and the selection
    is applied once the folder is loaded, unlike a detached `explorer /select` process.
    """
    item = c_void_p()
    _shell32.SHParseDisplayName(str(path), None, byref(item), 0, None)
    try:
        _shell32.SHOpenFolderAndSelectItems(item, 0, None, 0)
    finally:
        _ole32.CoTaskMemFree(item)
