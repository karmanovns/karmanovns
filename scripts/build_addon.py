#!/usr/bin/env python3
"""Create the Blender-installable ZIP without storing binary artifacts in Git."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ADDON_DIRECTORY = REPOSITORY_ROOT / "td_light_bridge"
OUTPUT_ARCHIVE = REPOSITORY_ROOT / "dist" / "td_light_bridge.zip"


def main():
    OUTPUT_ARCHIVE.parent.mkdir(exist_ok=True)
    with ZipFile(OUTPUT_ARCHIVE, "w", compression=ZIP_DEFLATED) as archive:
        for path in ADDON_DIRECTORY.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, path.relative_to(REPOSITORY_ROOT))
    print(f"Created {OUTPUT_ARCHIVE.relative_to(REPOSITORY_ROOT)}")


if __name__ == "__main__":
    main()
