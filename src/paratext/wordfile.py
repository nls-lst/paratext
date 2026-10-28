"""A small .docx writer: paragraphs, tables and native Word charts.

Each chart carries its data in an embedded workbook, so it can be edited or
copied into another document in Word. Stdlib only. `to_pdf` converts with
LibreOffice when it is installed.
"""

from __future__ import annotations

import io
import math
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

FONT = "Arial"
INK, INK2, MUTED, LINE = "0B0B0B", "52514E", "898781", "E1E0D9"
EMU_PER_CM = 360000
TWIPS_PER_CM = 567

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_PKG = "http://schemas.openxmlformats.org/package/2006"
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _x(s) -> str:
    return escape(str(s), {'"': "&quot;"})


# ── text ─────────────────────────────────────────────────────────────────────
def run(text: str, *, bold: bool = False, size: float | None = None,
        color: str | None = None) -> str:
    props = ("<w:b/>" if bold else "") + (f'<w:color w:val="{color}"/>' if color else "") \
        + (f'<w:sz w:val="{round(size * 2)}"/>' if size else "")
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{_x(text)}</w:t></w:r>'


def para(*parts: str, style: str | None = None, after: int | None = None,
         align: str | None = None, keep_next: bool = False) -> str:
    """A paragraph. Plain strings become runs; strings from `run()` pass through."""
    ppr = (f'<w:pStyle w:val="{style}"/>' if style else "") \
        + ("<w:keepNext/>" if keep_next else "") \
        + (f'<w:spacing w:after="{after}"/>' if after is not None else "") \
        + (f'<w:jc w:val="{align}"/>' if align else "")
    body = "".join(p if p.startswith("<w:") else run(p) for p in parts)
    return f"<w:p>{f'<w:pPr>{ppr}</w:pPr>' if ppr else ''}{body}</w:p>"


def table(rows: list[list[str]], widths_cm: list[float], *, header: bool = False,
          lines: bool = True, align: list[str] | None = None) -> str:
    """Cells are text, or paragraph XML from `para()`."""
    tw = [round(w * TWIPS_PER_CM) for w in widths_cm]
    none = "".join(f'<w:{s} w:val="nil"/>' for s in
                   ("top", "left", "bottom", "right", "insideH", "insideV"))
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="{sum(tw)}" w:type="dxa"/>'
           f'<w:tblBorders>{none}</w:tblBorders><w:tblLayout w:type="fixed"/>'
           f'<w:tblCellMar><w:left w:w="0" w:type="dxa"/><w:right w:w="113" w:type="dxa"/>'
           f'</w:tblCellMar></w:tblPr><w:tblGrid>'
           + "".join(f'<w:gridCol w:w="{w}"/>' for w in tw) + "</w:tblGrid>"]
    for i, row in enumerate(rows):
        head = header and i == 0
        out.append("<w:tr>" + ("<w:trPr><w:tblHeader/></w:trPr>" if head else ""))
        for j, cell in enumerate(row):
            border = ""
            if lines and i < len(rows) - 1:
                border = (f'<w:tcBorders><w:bottom w:val="single" w:sz="4" '
                          f'w:color="{MUTED if head else LINE}"/></w:tcBorders>')
            jc = align[j] if align else None
            if not cell.startswith("<w:"):
                cell = para(run(cell, bold=head, color=INK2 if head else None),
                            style="TableText", align=jc if jc != "left" else None)
            out.append(f'<w:tc><w:tcPr><w:tcW w:w="{tw[j]}" w:type="dxa"/>{border}'
                       f'<w:vAlign w:val="center"/></w:tcPr>{cell}</w:tc>')
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out) + para(style="Gap")


# ── charts ───────────────────────────────────────────────────────────────────
def _col(i: int) -> str:
    return "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[i]


def _txpr(size: float = 8, color: str = INK2) -> str:
    return (f'<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="{round(size * 100)}">'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f'<a:latin typeface="{FONT}"/></a:defRPr></a:pPr><a:endParaRPr lang="en-GB"/>'
            f'</a:p></c:txPr>')


def _str_ref(ref: str, vals: list) -> str:
    pts = "".join(f'<c:pt idx="{i}"><c:v>{_x(v)}</c:v></c:pt>' for i, v in enumerate(vals))
    return (f'<c:strRef><c:f>{ref}</c:f><c:strCache><c:ptCount val="{len(vals)}"/>{pts}'
            f'</c:strCache></c:strRef>')


def _num_ref(ref: str, vals: list) -> str:
    pts = "".join(f'<c:pt idx="{i}"><c:v>{round(v, 4)}</c:v></c:pt>'
                  for i, v in enumerate(vals) if v is not None)
    return (f'<c:numRef><c:f>{ref}</c:f><c:numCache><c:formatCode>General</c:formatCode>'
            f'<c:ptCount val="{len(vals)}"/>{pts}</c:numCache></c:numRef>')


def _fill(color: str) -> str:
    return f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'


def _series(i: int, s: dict, cats: list, kind: str, labels: str | None = None) -> str:
    n = len(cats)
    col = _col(i + 1)
    if kind == "line":
        dash = '<a:prstDash val="sysDash"/>' if s.get("dashed") else ""
        sppr = (f'<c:spPr><a:ln w="{s.get("width", 19050)}" cap="rnd">{_fill(s["color"])}'
                f'{dash}<a:round/></a:ln></c:spPr><c:marker><c:symbol val="none"/></c:marker>')
    elif kind == "doughnut":
        sppr = "".join(
            f'<c:dPt><c:idx val="{j}"/><c:bubble3D val="0"/><c:spPr>{_fill(c)}'
            f'<a:ln w="12700">{_fill("FFFFFF")}</a:ln></c:spPr></c:dPt>'
            for j, c in enumerate(s["colors"]))
    else:
        sppr = (f'<c:spPr>{_fill(s["color"])}<a:ln w="9525">{_fill("FFFFFF")}</a:ln></c:spPr>'
                f'<c:invertIfNegative val="0"/>')
    dl = ""
    if labels:
        dl = (f'<c:dLbls><c:numFmt formatCode="{_x(labels)}" sourceLinked="0"/>'
              f'<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>{_txpr(8, INK)}'
              f'<c:dLblPos val="outEnd"/><c:showLegendKey val="0"/><c:showVal val="1"/>'
              f'<c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/>'
              f'<c:showBubbleSize val="0"/></c:dLbls>')
    return (f'<c:ser><c:idx val="{i}"/><c:order val="{i}"/>'
            f'<c:tx>{_str_ref(f"Sheet1!${col}$1", [s["name"]])}</c:tx>{sppr}{dl}'
            f'<c:cat>{_str_ref(f"Sheet1!$A$2:$A${n + 1}", cats)}</c:cat>'
            f'<c:val>{_num_ref(f"Sheet1!${col}$2:${col}${n + 1}", s["values"])}</c:val>'
            + ('<c:smooth val="0"/>' if kind == "line" else "") + "</c:ser>")


def chart_xml(spec: dict) -> str:
    """spec: type (col | bar | line | doughnut), categories, series [{name, values,
    color}], and optionally stacked, threshold {name, value, color}, ymax, yfmt,
    ystep, legend, labels (a number format), skip (show every nth category)."""
    kind, cats, series = spec["type"], spec["categories"], spec["series"]
    axes = '<c:axId val="1"/><c:axId val="2"/>'
    if kind == "doughnut":
        plot = (f'<c:doughnutChart><c:varyColors val="1"/>{_series(0, series[0], cats, kind)}'
                f'<c:firstSliceAng val="0"/><c:holeSize val="62"/></c:doughnutChart>')
    else:
        if kind == "line":
            plot = ('<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>'
                    + "".join(_series(i, s, cats, "line") for i, s in enumerate(series))
                    + f'<c:marker val="1"/>{axes}</c:lineChart>')
        else:
            stacked = spec.get("stacked")
            plot = (f'<c:barChart><c:barDir val="{kind}"/>'
                    f'<c:grouping val="{"stacked" if stacked else "clustered"}"/>'
                    f'<c:varyColors val="0"/>'
                    + "".join(_series(i, s, cats, "bar", spec.get("labels"))
                              for i, s in enumerate(series))
                    + f'<c:gapWidth val="{spec.get("gap", 40)}"/>'
                    + ('<c:overlap val="100"/>' if stacked else "") + f"{axes}</c:barChart>")
        thr = spec.get("threshold")
        if thr:
            line = {"name": thr["name"], "values": [thr["value"]] * len(cats),
                    "color": thr.get("color", INK), "dashed": True, "width": 15875}
            plot += ('<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>'
                     + _series(len(series), line, cats, "line")
                     + f'<c:marker val="1"/>{axes}</c:lineChart>')
        horiz = kind == "bar"
        skip = spec.get("skip")
        ln = f'<c:spPr><a:ln w="9525">{_fill(LINE)}</a:ln></c:spPr>'
        no_ln = '<c:spPr><a:ln><a:noFill/></a:ln></c:spPr>'
        plot += (
            f'<c:catAx><c:axId val="1"/><c:scaling><c:orientation '
            f'val="{"maxMin" if horiz else "minMax"}"/></c:scaling><c:delete val="0"/>'
            f'<c:axPos val="{"l" if horiz else "b"}"/>'
            f'<c:numFmt formatCode="General" sourceLinked="0"/><c:majorTickMark val="none"/>'
            f'<c:minorTickMark val="none"/><c:tickLblPos val="low"/>{ln}{_txpr()}'
            f'<c:crossAx val="2"/><c:crosses val="autoZero"/><c:auto val="1"/>'
            f'<c:lblAlgn val="ctr"/><c:lblOffset val="100"/>'
            + (f'<c:tickLblSkip val="{skip}"/><c:tickMarkSkip val="{skip}"/>' if skip else "")
            + '<c:noMultiLvlLbl val="0"/></c:catAx>'
            + '<c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/>'
            + (f'<c:max val="{spec["ymax"]}"/>' if spec.get("ymax") else "")
            + f'<c:min val="0"/></c:scaling><c:delete val="{1 if horiz else 0}"/>'
            f'<c:axPos val="{"b" if horiz else "l"}"/>'
            + ("" if horiz else f'<c:majorGridlines><c:spPr><a:ln w="6350">{_fill(LINE)}'
               f'</a:ln></c:spPr></c:majorGridlines>')
            + f'<c:numFmt formatCode="{_x(spec.get("yfmt", "General"))}" sourceLinked="0"/>'
            f'<c:majorTickMark val="none"/><c:minorTickMark val="none"/>'
            f'<c:tickLblPos val="nextTo"/>{no_ln}{_txpr()}<c:crossAx val="1"/>'
            f'<c:crosses val="autoZero"/><c:crossBetween val="between"/>'
            + (f'<c:majorUnit val="{spec["ystep"]}"/>' if spec.get("ystep") else "")
            + "</c:valAx>")
    legend = (f'<c:legend><c:legendPos val="b"/><c:overlay val="0"/>{_txpr()}</c:legend>'
              if spec.get("legend") else "")
    return (f'{_XML}<c:chartSpace xmlns:c="{_C}" xmlns:a="{_A}" xmlns:r="{_R}">'
            f'<c:roundedCorners val="0"/><c:chart><c:autoTitleDeleted val="1"/>'
            f'<c:plotArea><c:layout/>{plot}<c:spPr><a:noFill/></c:spPr></c:plotArea>{legend}'
            f'<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
            f'<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>{_txpr()}'
            f'<c:externalData r:id="rId1"><c:autoUpdate val="0"/></c:externalData>'
            f'</c:chartSpace>')


def workbook(spec: dict) -> bytes:
    """The chart's data as a one-sheet .xlsx, so Word can edit it."""
    series = list(spec["series"])
    if spec.get("threshold"):
        t = spec["threshold"]
        series.append({"name": t["name"], "values": [t["value"]] * len(spec["categories"])})
    rows = [["", *[s["name"] for s in series]]]
    rows += [[c, *[s["values"][i] for s in series]] for i, c in enumerate(spec["categories"])]

    def cell(ref: str, v) -> str:
        if v is None:
            return ""
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{round(v, 4)}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{_x(v)}</t></is></c>'

    sheet = "".join(
        f'<row r="{r + 1}">' + "".join(cell(f"{_col(c)}{r + 1}", v) for c, v in enumerate(row))
        + "</row>" for r, row in enumerate(rows))
    ss = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    parts = {
        "[Content_Types].xml": (
            f'{_XML}<Types xmlns="{_PKG}/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'),
        "_rels/.rels": (
            f'{_XML}<Relationships xmlns="{_PKG}/relationships"><Relationship Id="rId1" '
            f'Type="{_R}/officeDocument" Target="xl/workbook.xml"/></Relationships>'),
        "xl/workbook.xml": (
            f'{_XML}<workbook xmlns="{ss}" xmlns:r="{_R}"><sheets><sheet name="Sheet1" '
            f'sheetId="1" r:id="rId1"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": (
            f'{_XML}<Relationships xmlns="{_PKG}/relationships"><Relationship Id="rId1" '
            f'Type="{_R}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'),
        "xl/worksheets/sheet1.xml": f'{_XML}<worksheet xmlns="{ss}"><sheetData>{sheet}'
                                    f'</sheetData></worksheet>',
    }
    return _zip(parts)


def _zip(parts: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()


# ── document ─────────────────────────────────────────────────────────────────
class Doc:
    def __init__(self, title: str = "") -> None:
        self.title = title
        self.body: list[str] = []
        self.charts: list[dict] = []

    def add(self, *xml: str) -> None:
        self.body.extend(xml)

    def chart(self, spec: dict, width_cm: float, height_cm: float) -> str:
        """Paragraph XML holding the chart, to `add()` or put in a table cell."""
        self.charts.append(spec)
        n = len(self.charts)
        cx, cy = round(width_cm * EMU_PER_CM), round(height_cm * EMU_PER_CM)
        return (f'<w:p><w:pPr><w:pStyle w:val="Chart"/></w:pPr><w:r><w:drawing>'
                f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
                f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
                f'<wp:docPr id="{n}" name="Chart {n}"/><wp:cNvGraphicFramePr/>'
                f'<a:graphic xmlns:a="{_A}"><a:graphicData uri="{_C}">'
                f'<c:chart xmlns:c="{_C}" r:id="rIdChart{n}"/></a:graphicData></a:graphic>'
                f'</wp:inline></w:drawing></w:r></w:p>')

    def save(self, path: Path) -> Path:
        n = len(self.charts)
        margin = 2 * TWIPS_PER_CM
        doc = (f'{_XML}<w:document xmlns:w="{_W}" xmlns:r="{_R}" xmlns:wp="{_WP}"><w:body>'
               + "".join(self.body)
               + f'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="{margin}" '
               f'w:right="{margin}" w:bottom="{margin}" w:left="{margin}" w:header="709" '
               f'w:footer="709" w:gutter="0"/></w:sectPr></w:body></w:document>')
        ct = (f'{_XML}<Types xmlns="{_PKG}/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
              'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
              '<Default Extension="xlsx" ContentType="application/vnd.openxmlformats-'
              'officedocument.spreadsheetml.sheet"/>'
              '<Override PartName="/word/document.xml" ContentType="application/vnd.'
              'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
              '<Override PartName="/word/styles.xml" ContentType="application/vnd.'
              'openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
              '<Override PartName="/docProps/core.xml" ContentType="application/vnd.'
              'openxmlformats-package.core-properties+xml"/>'
              + "".join(f'<Override PartName="/word/charts/chart{i}.xml" ContentType="'
                        f'application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>'
                        for i in range(1, n + 1)) + "</Types>")
        rels = (f'{_XML}<Relationships xmlns="{_PKG}/relationships">'
                f'<Relationship Id="rId1" Type="{_R}/officeDocument" '
                f'Target="word/document.xml"/><Relationship Id="rId2" '
                f'Type="{_PKG}/relationships/metadata/core-properties" '
                f'Target="docProps/core.xml"/></Relationships>')
        doc_rels = (f'{_XML}<Relationships xmlns="{_PKG}/relationships">'
                    f'<Relationship Id="rIdStyles" Type="{_R}/styles" Target="styles.xml"/>'
                    + "".join(f'<Relationship Id="rIdChart{i}" Type="{_R}/chart" '
                              f'Target="charts/chart{i}.xml"/>' for i in range(1, n + 1))
                    + "</Relationships>")
        core = (f'{_XML}<cp:coreProperties xmlns:cp="{_PKG}/metadata/core-properties" '
                f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{_x(self.title)}'
                f'</dc:title><dc:creator>paratext</dc:creator></cp:coreProperties>')
        parts: dict[str, str | bytes] = {
            "[Content_Types].xml": ct, "_rels/.rels": rels, "docProps/core.xml": core,
            "word/document.xml": doc, "word/styles.xml": _STYLES,
            "word/_rels/document.xml.rels": doc_rels,
        }
        for i, spec in enumerate(self.charts, 1):
            parts[f"word/charts/chart{i}.xml"] = chart_xml(spec)
            parts[f"word/charts/_rels/chart{i}.xml.rels"] = (
                f'{_XML}<Relationships xmlns="{_PKG}/relationships"><Relationship Id="rId1" '
                f'Type="{_R}/package" Target="../embeddings/Microsoft_Excel_Worksheet{i}.xlsx"/>'
                f'</Relationships>')
            parts[f"word/embeddings/Microsoft_Excel_Worksheet{i}.xlsx"] = workbook(spec)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_zip(parts))
        return path


def _style(sid: str, name: str, *, size: float, bold: bool = False, color: str = INK,
           before: int = 0, after: int = 80, keep: bool = False, outline: int | None = None,
           basic: bool = False) -> str:
    ppr = ("<w:keepNext/>" if keep else "") \
        + f'<w:spacing w:before="{before}" w:after="{after}"/>' \
        + (f'<w:outlineLvl w:val="{outline}"/>' if outline is not None else "")
    rpr = ("<w:b/>" if bold else "") \
        + f'<w:color w:val="{color}"/><w:sz w:val="{round(size * 2)}"/>'
    based = "" if basic else '<w:basedOn w:val="Normal"/>'
    return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/>{based}'
            f'<w:qFormat/><w:pPr>{ppr}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>')


_STYLES = (
    f'{_XML}<w:styles xmlns:w="{_W}"><w:docDefaults><w:rPrDefault><w:rPr>'
    f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/><w:color w:val="{INK}"/>'
    f'<w:sz w:val="19"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>'
    f'<w:spacing w:after="80" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
    f'</w:docDefaults>'
    + _style("Normal", "Normal", size=9.5, basic=True)
    + _style("Title", "Title", size=20, bold=True, after=40)
    + _style("Heading1", "heading 1", size=12.5, bold=True, before=360, after=40, keep=True,
             outline=0)
    + _style("Heading2", "heading 2", size=9, bold=True, color=INK2, before=160, after=20,
             keep=True, outline=1)
    + _style("Note", "Note", size=8.5, color=INK2, after=60)
    + _style("TableText", "Table text", size=8.5, after=0)
    + _style("Chart", "Chart", size=9.5, after=0)
    + _style("Gap", "Gap", size=4, after=0)
    + "</w:styles>"
)


def to_pdf(docx: Path, timeout: float = 180) -> Path | None:
    """Convert with LibreOffice. None when it isn't installed or the conversion fails."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    pdf = docx.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        try:
            subprocess.run(
                [exe, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless",
                 "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
                capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
    return pdf if pdf.is_file() else None


def nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e
