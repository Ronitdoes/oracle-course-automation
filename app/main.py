"""Desktop entry point: python -m app.main"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def main() -> int:
    base = _base_dir()
    # Run exe-adjacent first so portable .exe finds its .env + artifacts.
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    os.chdir(str(base))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    try:
        (base / "artifacts").mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(base / "artifacts" / "agent.log"), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(fh)
    except Exception:
        pass

    # Ensure a .env exists (copy example for first-run portability).
    try:
        env = base / ".env"
        example = base / ".env.example"
        if not env.exists() and example.exists():
            env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass

    from PySide6.QtWidgets import QApplication
    from app.logo import build_icon
    from app.main_window import MainWindow
    from app.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName("Browser Agent")
    app.setOrganizationName("BrowserAgent")
    app.setWindowIcon(build_icon())
    apply_theme(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
