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


def svgs_to_pdf(svgs, out_pdf, page_w_mm=210, page_h_mm=297):
    c = rl_canvas.Canvas(out_pdf, pagesize=(page_w_mm * mm, page_h_mm * mm))
    for svg in svgs:
        drw = svg2rlg(io.StringIO(svg))
        if drw is None:
            continue
        # svglib keeps verovio's viewBox units; scale to the page
        sx = (page_w_mm * mm) / drw.width
        sy = (page_h_mm * mm) / drw.height
        drw.scale(sx, sy)
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
