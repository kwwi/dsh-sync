#!/usr/bin/env python3
"""
Score rendering pipeline: MusicXML -> engraved PDF (via Verovio SVG + svglib)
and MusicXML -> MIDI (via music21).
"""
import os, io
import verovio
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.units import mm
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF


def musicxml_to_svgs(xml_path, page_w_mm=210, page_h_mm=297,
                     margin_mm=12, scale=42, breaks="auto"):
    """Render a MusicXML file to a list of SVG strings, one per page."""
    tk = verovio.toolkit()
    tk.setResourcePath(os.path.join(os.path.dirname(verovio.__file__), "data"))
    ok = tk.loadFile(xml_path)
    if not ok:
        raise RuntimeError("verovio failed to load " + xml_path)
    tk.setOptions({
        "pageWidth": int(page_w_mm * 10),
        "pageHeight": int(page_h_mm * 10),
        "pageMarginLeft": int(margin_mm * 10),
        "pageMarginRight": int(margin_mm * 10),
        "pageMarginTop": int(margin_mm * 10),
        "pageMarginBottom": int(margin_mm * 10),
        "scale": scale,
        "adjustPageHeight": False,
        "svgViewBox": True,
        "svgHtml5": False,
        "breaks": breaks,
    })
    tk.redoLayout()
    n = tk.getPageCount()
    return [tk.renderToSVG(i + 1) for i in range(n)]


def svgs_to_pdf(svgs, out_pdf, page_w_mm=210, page_h_mm=297, margin_mm=12):
    """
    Place each engraved page on a PDF page.

    svglib keeps Verovio's drawing coordinates, whose origin is not the page
    origin - the content can start at a negative x, and drawing it at (0, 0)
    would silently clip the left edge (a centred title loses its first
    characters). The drawing is therefore fitted and shifted by its own
    bounding box instead of by its nominal width and height.
    """
    c = rl_canvas.Canvas(out_pdf, pagesize=(page_w_mm * mm, page_h_mm * mm))
    for svg in svgs:
        drw = svg2rlg(io.StringIO(svg))
        if drw is None:
            continue
        x1, y1, x2, y2 = drw.getBounds()
        bw, bh = max(x2 - x1, 1e-6), max(y2 - y1, 1e-6)
        avail_w = (page_w_mm - 2 * margin_mm) * mm
        avail_h = (page_h_mm - 2 * margin_mm) * mm
        s = min(avail_w / bw, avail_h / bh)
        drw.scale(s, s)
        x1, y1, x2, y2 = drw.getBounds()
        # centre horizontally, sit near the top margin
        dx = margin_mm * mm - x1
        dy = (page_h_mm - margin_mm) * mm - y2
        drw.translate(dx, dy)
        renderPDF.draw(drw, c, 0, 0)
        c.showPage()
    c.save()
    return out_pdf


def render(xml_path, out_pdf, **kw):
    svgs = musicxml_to_svgs(xml_path, **kw)
    return svgs_to_pdf(svgs, out_pdf,
                       kw.get("page_w_mm", 210), kw.get("page_h_mm", 297)), len(svgs)


if __name__ == "__main__":
    import sys
    xml = sys.argv[1]
    out = sys.argv[2]
    p, n = render(xml, out)
    print(f"wrote {p} ({n} pages)")
