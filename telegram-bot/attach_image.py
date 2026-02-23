#!/usr/bin/env python3
"""
Copy image file(s) into the bot's pending_images directory. The next time the
bot sends an assistant reply, it will send these images to you on Telegram and
then delete them.

Usage:
  python3 attach_image.py /path/to/image.png
  python3 attach_image.py screenshot1.png screenshot2.png

Use this when you want to send images (e.g. browser screenshots) with the
next bot reply.
"""

import os
import shutil
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PENDING_IMAGES_DIR = os.path.join(SCRIPT_DIR, "pending_images")


def main():
    if len(sys.argv) < 2:
        print("Usage: attach_image.py <image> [image ...]", file=sys.stderr)
        sys.exit(1)
    os.makedirs(PENDING_IMAGES_DIR, mode=0o700, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    for i, src in enumerate(sys.argv[1:]):
        if not os.path.isfile(src):
            print("attach_image: not a file:", src, file=sys.stderr)
            continue
        base = os.path.basename(src)
        name, ext = os.path.splitext(base)
        if not ext or ext.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            print("attach_image: skipping non-image:", src, file=sys.stderr)
            continue
        dest_name = f"{name}_{stamp}_{i}{ext}" if i else f"{name}_{stamp}{ext}"
        dest = os.path.join(PENDING_IMAGES_DIR, dest_name)
        shutil.copy2(src, dest)
        print(dest)


if __name__ == "__main__":
    main()
