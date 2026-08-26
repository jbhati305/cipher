#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "alexa"


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "interaction-models").mkdir(parents=True)
    shutil.copytree(
        ROOT / "alexa/interaction-models", DIST / "interaction-models", dirs_exist_ok=True
    )
    shutil.copy2(ROOT / "alexa/skill-package/skill.json", DIST / "skill.json")
    print(f"Skill assets ready for manual import into the Alexa Developer Console: {DIST}")


if __name__ == "__main__":
    main()
