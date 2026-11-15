"""Build a character atlas from labelled user examples and installed digit fonts.

This creates model data, not application test results. Coordinates themselves
are never stored in the recognizer: only normalized individual digits 0–9.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kodlar.glyph_ocr import Glyph, segment, fingerprint, components

SAMPLES = [
    ('karos-67.png', (15, 16, 82, 16), '676775'),
    ('karos-69.png', (39, 23, 81, 17), '690871'),
    ('karos-76.png', (10, 10, 82, 18), '766612'),
    ('karos-75.png', (26, 25, 81, 17), '757530'),
    ('karos-stable.png', (33, 33, 96, 23), '719572'),
    ('karos-77.png', (12, 8, 97, 18), '770562'),
    ('karos-85.png', None, '853508'),
]

PS = r'''
Add-Type -AssemblyName System.Drawing
$requests=[Console]::ReadLine() | ConvertFrom-Json
function Plane($bitmap) {
 $data=New-Object byte[] ($bitmap.Width*$bitmap.Height)
 for($y=0;$y -lt $bitmap.Height;$y++) {for($x=0;$x -lt $bitmap.Width;$x++) {
  $c=$bitmap.GetPixel($x,$y)
  $lo=[Math]::Min($c.R,[Math]::Min($c.G,$c.B));$hi=[Math]::Max($c.R,[Math]::Max($c.G,$c.B))
  if($hi-$lo -le 65) {$data[$y*$bitmap.Width+$x]=$lo}
 }}
 return [Convert]::ToBase64String($data)
}
foreach($request in $requests) {
 $original=[Drawing.Bitmap]::FromFile($request.path)
 try {
  $bitmap=$original
  if($request.region) {$r=$request.region;$bitmap=$original.Clone([Drawing.Rectangle]::new($r[0],$r[1],$r[2],$r[3]),[Drawing.Imaging.PixelFormat]::Format32bppArgb)}
  @{label=$request.label;width=$bitmap.Width;height=$bitmap.Height;pixels=(Plane $bitmap);source='capture'} | ConvertTo-Json -Compress
  if($bitmap -ne $original) {$bitmap.Dispose()}
 } finally {$original.Dispose()}
}
foreach($family in @('Arial','Tahoma','Segoe UI','Verdana')) {
 foreach($size in @(9,11,13,15)) {foreach($label in 0..9) {
  $bitmap=[Drawing.Bitmap]::new(30,30)
  $graphics=[Drawing.Graphics]::FromImage($bitmap)
  $font=[Drawing.Font]::new($family,$size,[Drawing.FontStyle]::Regular,[Drawing.GraphicsUnit]::Pixel)
  try {
   $graphics.Clear([Drawing.Color]::Black)
   $graphics.TextRenderingHint=[Drawing.Text.TextRenderingHint]::AntiAliasGridFit
   $graphics.DrawString([string]$label,$font,[Drawing.Brushes]::White,0,0)
   @{label=[string]$label;width=30;height=30;pixels=(Plane $bitmap);source='font'} | ConvertTo-Json -Compress
  } finally {$font.Dispose();$graphics.Dispose();$bitmap.Dispose()}
 }}
}
'''


def build():
    import base64
    requests = [dict(path=str(ROOT/'kodlar/tests/fixtures'/name), region=region, label=label)
                for name, region, label in SAMPLES]
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', PS],
        input=json.dumps(requests), text=True, encoding='utf-8', capture_output=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
    templates = set()
    capture_digits = set()
    for line in result.stdout.splitlines():
        item = json.loads(line)
        plane = base64.b64decode(item['pixels'])
        w, h = item['width'], item['height']
        for threshold in (110, 130, 150, 170, 190):
            if item['source'] == 'font':
                matrix = [tuple(value >= threshold for value in plane[y*w:(y+1)*w]) for y in range(h)]
                glyphs = [glyph for glyph in components(matrix) if glyph.height >= 4]
                sequences = [glyphs] if len(glyphs) == 1 else []
            else:
                sequences = [[glyph for glyph in tokens if glyph.kind == 'digit']
                             for tokens in segment(plane, w, h, threshold)
                             if [glyph.kind for glyph in tokens if glyph.kind != '/'] ==
                                ['digit','digit','.','digit','digit','digit','.','digit']]
            for glyphs in sequences:
                if len(glyphs) != len(item['label']):
                    continue
                for label, glyph in zip(item['label'], glyphs):
                    bits, ratio, holes = fingerprint(glyph)
                    templates.add((label, f'{bits:x}', round(ratio, 5), holes))
                    if item['source'] == 'capture':
                        capture_digits.add(label)
    output = ROOT/'kodlar/coordinate_font_data.py'
    lines = ['"""Generated numeric glyph atlas; rebuild with scripts/build_coordinate_font.py."""', '', 'TEMPLATES = (']
    lines += ['    '+repr(template)+',' for template in sorted(templates)]
    lines += [')', '']
    output.write_text('\n'.join(lines), encoding='utf-8')
    print(f'Built {len(templates)} digit shapes; capture glyph coverage: {"".join(sorted(capture_digits))}')


if __name__ == '__main__':
    build()
