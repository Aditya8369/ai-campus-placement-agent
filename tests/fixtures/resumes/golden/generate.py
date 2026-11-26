"""Rebuild the fictional binary résumé fixtures and their authored expectations."""

import json
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml.ns import qn
from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

HERE = Path(__file__).resolve().parent

# Each pair uses the same fictional facts in two real document formats.
PROFILES = {
    "single_column": (
        ("Education", "Fictional Cedar College", "Bachelor of Computing"),
        ("Technical Skills", "Python, Flask, PostgreSQL", ""),
        ("Projects", "Seedling Catalogue", "Catalogued a fictional collection of seedlings."),
    ),
    "two_columns": (
        ("Education", "Fictional Dune Academy", "Diploma in Computing"),
        ("Technical Skills", "Java, Maven, Git", ""),
        ("Projects", "Dune Atlas", "Indexed a fictional set of dune survey records."),
    ),
    "table": (
        ("Education", "Fictional Fern College", "Bachelor of Computer Science"),
        ("Technical Skills", "TypeScript, React, SQL", ""),
        ("Projects", "Fern Inventory", "Organized a fictional stock of fern species."),
    ),
    "unusual_headings": (
        ("Academic Credentials", "Fictional Kite Institute", "Diploma in Information Systems"),
        ("Core Competencies", "Python, Django, Redis", ""),
        ("Portfolio Projects", "Wind Journal", "Displayed fictional wind readings."),
    ),
    "two_pages": (
        ("Education", "Fictional Quartz Academy", "Bachelor of Data Science"),
        ("Technical Skills", "Python, Pandas, NumPy", ""),
        ("Projects", "Quartz Notebook", "Summarized a fictional set of mineral samples."),
    ),
}

HEADERS = ("education", "skills", "projects")


def scanned_image():
    """Draw text as pixels so the resulting document has no text layer."""
    image = Image.new("RGB", (520, 130), "white")
    ImageDraw.Draw(image).multiline_text(
        (16, 18),
        "FICTIONAL CANDIDATE\nEDUCATION\nFictional Clay College\nSKILLS\nPython, SQL",
        fill="black",
        spacing=5,
    )
    return image


def render_pdf(path, layout, profile):
    pdf = Canvas(str(path), pagesize=(612, 792), invariant=True)
    pdf.setTitle("Fictional résumé fixture")
    if layout == "scanned_image":
        pdf.drawImage(ImageReader(scanned_image()), 45, 635)
    else:
        pdf.drawString(45, 750, "Fictional Candidate for Parser Testing")
        x, y = 45, 712
        for index, (heading, first, second) in enumerate(profile):
            if layout == "two_columns" and index == 2:
                x, y = 330, 712
            if layout == "two_pages" and index == 2:
                pdf.showPage()
                y = 745
            pdf.setFont("Helvetica-Bold", 12)
            pdf.drawString(x, y, heading)
            pdf.setFont("Helvetica", 10)
            if layout == "table":
                pdf.rect(x, y - 42, 505, 27)
                pdf.line(x + 200, y - 42, x + 200, y - 15)
                pdf.drawString(x + 5, y - 32, first)
                pdf.drawString(x + 205, y - 32, second)
            else:
                pdf.drawString(x, y - 20, first)
                if second:
                    pdf.drawString(x, y - 35, second)
            y -= 80
    pdf.save()


def render_docx(path, layout, profile):
    document = Document()
    document.core_properties.title = "Fictional résumé fixture"
    document.core_properties.author = "Parser fixture generator"
    if layout == "scanned_image":
        pixels = BytesIO()
        scanned_image().save(pixels, "PNG")
        pixels.seek(0)
        document.add_picture(pixels)
    else:
        document.add_paragraph("Fictional Candidate for Parser Testing")
        if layout == "two_columns":
            columns = document.sections[0]._sectPr.find(qn("w:cols"))
            columns.set(qn("w:num"), "2")
        for index, (heading, first, second) in enumerate(profile):
            if layout == "two_columns" and index == 2:
                document.add_paragraph().add_run().add_break(WD_BREAK.COLUMN)
            if layout == "two_pages" and index == 2:
                document.add_page_break()
            if layout == "table":
                table = document.add_table(rows=2, cols=2)
                table.cell(0, 0).merge(table.cell(0, 1)).text = heading
                table.cell(1, 0).text = first
                table.cell(1, 1).text = second
            else:
                document.add_heading(heading, level=2)
                document.add_paragraph(first)
                if second:
                    document.add_paragraph(second)
    document.save(path)


def main():
    cases = {}
    for layout, profile in {**PROFILES, "scanned_image": None}.items():
        for suffix, render in (("pdf", render_pdf), ("docx", render_docx)):
            name = f"{layout}.{suffix}"
            render(HERE / name, layout, profile)
            if profile is None:
                cases[name] = {"image_only": True}
                continue
            cases[name] = {
                "sections": {
                    section: [phrase for phrase in item[1:] if phrase]
                    for section, item in zip(HEADERS, profile)
                },
                "skills": profile[1][1].split(", "),
            }
    (HERE / "expected.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
