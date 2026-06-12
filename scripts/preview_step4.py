"""Quick preview: launches the Imager and jumps straight to Step 4.

Bypasses Steps 1-3 validation so the operator can inspect the
Customize UI live (pulse animation, warning popup, etc.) without
needing a real SD card or golden image.

Run:
    .venv\\Scripts\\python.exe scripts\\preview_step4.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astromechos_imager.ui.app import build_app  # noqa: E402


def main() -> int:
    app, engine, state = build_app()
    window = engine.rootObjects()[0]
    window.show()

    # Sequential workflow: the legacy mode picker is gone; we just jump
    # straight to the customise step.

    # Skip splash + jump to Step 4 (Customize) after a short delay
    # to let the splash auto-advance timer settle.
    def jump():
        state.goto(4)

    QTimer.singleShot(1700, jump)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
