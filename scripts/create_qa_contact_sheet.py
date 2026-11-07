"""Create local visual-QA sheets from exported report page PNGs."""
from pathlib import Path
import json
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / 'tmp/source-form-qa-20261020'
evidence = json.loads((root / 'evidence.json').read_text(encoding='utf-8'))
outputs = [image for item in evidence['exports'] if item['filename'].endswith('.docx')
           for image in sorted(root.glob(Path(item['filename']).stem + '-*.png'))]
for name, files in [('contact-sheet.png', outputs), ('reference-contact-sheet.png', sorted(root.glob('reference-*.png')))]:
    if not files:
        continue
    width, height = 354, 520
    sheet = Image.new('RGB', (width * 4, height * ((len(files) + 3) // 4)), 'white')
    draw = ImageDraw.Draw(sheet)
    for i, path in enumerate(files):
        with Image.open(path) as image:
            image.thumbnail((width - 12, height - 25))
            x, y = (i % 4) * width, (i // 4) * height
            sheet.paste(image, (x, y + 20))
            label = ('reference' if path.name.startswith('reference') else 'comparison' if 'comparison' in path.name else 'inspection') + ' page ' + path.stem.split('-')[-1]
            draw.text((x + 4, y + 2), label, fill='black')
    sheet.save(root / name)
    print(root / name)
