from __future__ import annotations

from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


SAMPLES = {
    "t4_sample_2025": [
        "T4 Statement of Remuneration Paid",
        "Tax year: 2025",
        "Employee: Jordan Lee",
        "Employer: Northside Analytics Inc.",
        "",
        "Employment income (Box 14): 84,500.00",
        "Income tax deducted (Box 22): 19,250.00",
        "CPP contributions (Box 16): 3,754.45",
        "EI premiums (Box 18): 1,002.45",
        "Province of employment: Ontario",
    ],
    "t5_sample_2025": [
        "T5 Statement of Investment Income",
        "Tax year: 2025",
        "Recipient: Jordan Lee",
        "Payer: Maple Capital Corp.",
        "",
        "Interest from Canadian sources (Box 13): 1,325.40",
        "Taxable amount of eligible dividends (Box 24): 620.00",
        "Actual amount of eligible dividends (Box 25): 855.00",
        "Recipient account reference: INV-229103",
    ],
    "rrsp_receipt_2025": [
        "Official RRSP Contribution Receipt",
        "Tax year: 2025",
        "Contributor: Jordan Lee",
        "Issuer: Northern Trust Bank",
        "",
        "Total RRSP contributions: 9,000.00",
        "Contribution period: Mar 2025 - Dec 2025",
        "Receipt number: RRSP-2025-88142",
    ],
    "mixed_slips_bundle": [
        "Canadian Tax Slip Bundle",
        "Tax year: 2025",
        "",
        "--- T4 ---",
        "Employment income (Box 14): 93,000.00",
        "Income tax deducted (Box 22): 22,100.00",
        "",
        "--- T5 ---",
        "Interest from Canadian sources (Box 13): 880.25",
        "Taxable amount of eligible dividends (Box 24): 450.00",
        "",
        "--- RRSP ---",
        "Total RRSP contributions: 11,000.00",
    ],
    "edge_case_missing_fields": [
        "Tax Document (Edge Case)",
        "Tax year: 2025",
        "",
        "T4 Statement of Remuneration Paid",
        "Employment income (Box 14): 70,500.00",
        "",
        "Notes:",
        "- Some fields are intentionally omitted.",
        "- Use this file to test warning paths and partial extraction handling.",
    ],
}


def draw_form_image(lines: list[str], out_path: Path) -> None:
    width, height = 1700, 2200
    image = Image.new("RGB", (width, height), color=(248, 248, 245))
    draw = ImageDraw.Draw(image)

    try:
        font_title = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 48)
        font_body = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 32)
    except OSError:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()

    draw.rectangle((70, 70, width - 70, height - 70), outline=(45, 45, 45), width=5)
    draw.rectangle((100, 100, width - 100, 230), outline=(45, 45, 45), width=3)
    draw.text((130, 135), lines[0], fill=(10, 10, 10), font=font_title)

    y = 290
    for line in lines[1:]:
        if not line:
            y += 20
            continue
        draw.text((130, y), line, fill=(20, 20, 20), font=font_body)
        y += 58

    for _ in range(800):
        x = random.randint(0, width - 1)
        y_noise = random.randint(0, height - 1)
        shade = random.randint(230, 250)
        image.putpixel((x, y_noise), (shade, shade, shade))

    image = image.filter(ImageFilter.GaussianBlur(radius=0.35))
    suffix = out_path.suffix.lower()
    if suffix == ".png":
        image.save(out_path, format="PNG")
    elif suffix in {".jpg", ".jpeg"}:
        image.save(out_path, format="JPEG", quality=90)
    else:
        raise ValueError(f"Unsupported image output format: {out_path.suffix}")


def image_to_pdf(image_path: Path, pdf_path: Path) -> None:
    page_width, page_height = letter
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    reader = ImageReader(str(image_path))

    img_w, img_h = Image.open(image_path).size
    ratio = min((page_width - 60) / img_w, (page_height - 60) / img_h)
    draw_w = img_w * ratio
    draw_h = img_h * ratio
    x = (page_width - draw_w) / 2
    y = (page_height - draw_h) / 2

    c.drawImage(reader, x, y, width=draw_w, height=draw_h)
    c.showPage()
    c.save()


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    for name, lines in SAMPLES.items():
        png_path = base_dir / f"{name}.png"
        jpg_path = base_dir / f"{name}.jpg"
        jpeg_path = base_dir / f"{name}.jpeg"
        pdf_path = base_dir / f"{name}.pdf"

        draw_form_image(lines, png_path)
        draw_form_image(lines, jpg_path)
        draw_form_image(lines, jpeg_path)
        image_to_pdf(jpg_path, pdf_path)
        print(f"Generated {png_path.name}, {jpg_path.name}, {jpeg_path.name}, and {pdf_path.name}")


if __name__ == "__main__":
    main()
