"""Convert the PNG screenshots to WebP (quality 90) for the HTML manual (about 30 % smaller page).
Usage: convert_webp.py <png_dir> <webp_dir>   (any Python with Pillow, e.g. the Odoo Python)"""
import glob
import os
import sys

from PIL import Image

src, out = sys.argv[1:3]
os.makedirs(out, exist_ok=True)
total = 0
for path in sorted(glob.glob(os.path.join(src, '*.png'))):
    target = os.path.join(out, os.path.basename(path)[:-4] + '.webp')
    Image.open(path).convert('RGB').save(target, 'WEBP', quality=90, method=6)
    total += os.path.getsize(target)
print('WEBP', len(glob.glob(os.path.join(out, '*.webp'))), 'files', round(total / 1e6, 1), 'MB')
