"""《灰烬战争》外部可视化 MOD 配置与补丁器程序入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mod_configurator",
        description="《灰烬战争 (Dust Front RTS Demo)》外部可视化 MOD 配置与补丁器",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="自检 Python 版本、核心模块与 tkinter 可用性后退出",
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=None,
        help="手动指定 Dust Front RTS_Data 目录",
    )
    args = parser.parse_args(argv)

    if args.check:
        if sys.version_info < (3, 12):
            print(f"[ERROR] 需要 Python 3.12+，当前为 {sys.version}", file=sys.stderr)
            return 2
        import tkinter  # noqa: F401
        from . import backup_manager, gui, preset_manager, unity_assets  # noqa: F401

        print(
            f"[OK] mod_configurator v{__version__} 自检通过 "
            f"(Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}, "
            f"Tcl/Tk {tkinter.TclVersion})"
        )
        return 0

    from .gui import run_gui

    workspace_dir = Path(__file__).resolve().parent.parent
    return run_gui(workspace_dir=workspace_dir, initial_game_dir=args.game_dir)


if __name__ == "__main__":
    raise SystemExit(main())
