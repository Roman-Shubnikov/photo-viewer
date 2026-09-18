import subprocess
from pathlib import Path


def explorer_command(path: Path) -> str:
    return f'explorer /select,"{path}"'


def reveal_in_explorer(path: Path) -> None:
    """Opens the containing folder in Windows Explorer with the file selected."""
    subprocess.Popen(explorer_command(path))
