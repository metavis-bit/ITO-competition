"""
Word 教案预览工具 — 将 DOCX 转为结构化 HTML 用于浏览器内预览

两条路径:
  1. LibreOffice 可用时: docx → pdf → png 图片画廊（高保真）
  2. 回退: python-docx 解析为语义化 HTML（零外部依赖）

对应 A04 要求:
  - 5a) 提供课件预览功能，让教师审阅生成的教案草稿
"""

from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from docx import Document
from docx.oxml.ns import qn


# ═══════════════════════════════════════════
# 高保真预览（LibreOffice → PDF → PNG）
# ═══════════════════════════════════════════

def docx_to_images(docx_path: str, max_pages: int = 20, dpi: int = 150) -> List[str]:
    """将 DOCX 通过 LibreOffice 转为 PNG 图片列表。"""
    docx_path = str(docx_path)
    if not Path(docx_path).exists():
        return []

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "pdf",
                 "--outdir", tmp_dir, docx_path],
                capture_output=True, timeout=60,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        pdf_files = list(Path(tmp_dir).glob("*.pdf"))
        if not pdf_files:
            return []

        try:
            from pdf2image import convert_from_path
            images = convert_from_path(str(pdf_files[0]), dpi=dpi,
                                       first_page=1, last_page=max_pages)
        except Exception:
            return []

        out_dir = Path("outputs/docx_preview")
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = Path(docx_path).stem
        paths = []
        for i, img in enumerate(images):
            out_path = str(out_dir / f"{stem}_page_{i + 1}.png")
            img.save(out_path, "PNG")
            paths.append(out_path)

        return paths


# ═══════════════════════════════════════════
# 语义化 HTML 预览（零外部依赖回退）
# ═══════════════════════════════════════════

def docx_to_html(docx_path: str) -> str:
    """
    将 DOCX 解析为浏览器可渲染的 HTML 片段。

    支持: 标题层级、段落、粗体/斜体、表格、项目符号。
    """
    if not Path(docx_path).exists():
        return "<p>文件不存在</p>"

    try:
        doc = Document(docx_path)
    except Exception as e:
        return f"<p>DOCX 解析失败: {e}</p>"

    html_parts: List[str] = [
        '<div style="font-family:Microsoft YaHei,sans-serif;max-width:800px;'
        'margin:0 auto;padding:24px;line-height:1.8;color:#1a1a1a;">'
    ]

    for element in doc.element.body:
        tag = element.tag.split("}")[-1]  # strip namespace

        if tag == "p":
            html_parts.append(_render_paragraph(element, doc))
        elif tag == "tbl":
            html_parts.append(_render_table(element))

    html_parts.append("</div>")
    return "\n".join(html_parts)


def _render_paragraph(p_elem, doc: Document) -> str:
    """渲染单个段落为 HTML。"""
    # 检测标题级别
    pPr = p_elem.find(qn("w:pPr"))
    heading_level = 0
    is_list_item = False

    if pPr is not None:
        pStyle = pPr.find(qn("w:pStyle"))
        if pStyle is not None:
            style_val = pStyle.get(qn("w:val"), "")
            # Heading1 ~ Heading9
            if style_val.startswith("Heading"):
                try:
                    heading_level = int(style_val.replace("Heading", ""))
                except ValueError:
                    pass
            elif "List" in style_val or "Bullet" in style_val:
                is_list_item = True

        numPr = pPr.find(qn("w:numPr"))
        if numPr is not None:
            is_list_item = True

    # 提取文本 runs
    runs_html = []
    for r in p_elem.findall(qn("w:r")):
        text_elem = r.find(qn("w:t"))
        if text_elem is None or not text_elem.text:
            continue
        text = text_elem.text

        rPr = r.find(qn("w:rPr"))
        bold = False
        italic = False
        if rPr is not None:
            bold = rPr.find(qn("w:b")) is not None
            italic = rPr.find(qn("w:i")) is not None

        fragment = _escape(text)
        if bold:
            fragment = f"<b>{fragment}</b>"
        if italic:
            fragment = f"<i>{fragment}</i>"
        runs_html.append(fragment)

    content = "".join(runs_html)
    if not content.strip():
        return ""

    if heading_level:
        level = min(heading_level, 6)
        sizes = {1: "1.6em", 2: "1.35em", 3: "1.15em", 4: "1.05em", 5: "1em", 6: "0.95em"}
        return (
            f'<h{level} style="font-size:{sizes.get(level, "1em")};'
            f'margin:18px 0 8px;color:#1e3a5f;border-bottom:'
            f'{"2px solid #3b82f6" if level <= 2 else "none"};'
            f'padding-bottom:{"6px" if level <= 2 else "0"};">'
            f'{content}</h{level}>'
        )

    if is_list_item:
        return f'<p style="margin:4px 0 4px 24px;">• {content}</p>'

    return f'<p style="margin:6px 0;text-indent:2em;">{content}</p>'


def _render_table(tbl_elem) -> str:
    """渲染表格为 HTML。"""
    html = (
        '<table style="width:100%;border-collapse:collapse;margin:12px 0;'
        'font-size:0.9em;">'
    )

    rows = tbl_elem.findall(qn("w:tr"))
    for r_idx, tr in enumerate(rows):
        html += "<tr>"
        cells = tr.findall(qn("w:tc"))
        for tc in cells:
            # 提取单元格文本
            texts = []
            for p in tc.findall(qn("w:p")):
                p_text = []
                for r in p.findall(qn("w:r")):
                    t = r.find(qn("w:t"))
                    if t is not None and t.text:
                        p_text.append(t.text)
                texts.append("".join(p_text))
            cell_text = _escape("<br>".join(t for t in texts if t))

            tag = "th" if r_idx == 0 else "td"
            bg = "background:#f0f4f8;" if r_idx == 0 else ""
            html += (
                f'<{tag} style="border:1px solid #cbd5e1;padding:8px 10px;'
                f'{bg}font-weight:{"600" if r_idx == 0 else "normal"};">'
                f'{cell_text}</{tag}>'
            )
        html += "</tr>"

    html += "</table>"
    return html


def _escape(text: str) -> str:
    """HTML-escape，但保留 <br> 标签。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("&lt;br&gt;", "<br>")
    )


# ═══════════════════════════════════════════
# 统一预览入口
# ═══════════════════════════════════════════

def docx_preview_html(docx_path: str, max_pages: int = 15) -> str:
    """
    生成教案预览 HTML。

    优先使用 LibreOffice 高保真图片；不可用时回退到语义化 HTML。
    """
    images = docx_to_images(docx_path, max_pages=max_pages, dpi=120)

    if images:
        html_parts = [
            '<div style="display:flex;flex-direction:column;gap:12px;padding:8px;">'
        ]
        for i, img_path in enumerate(images):
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            html_parts.append(
                f'<div style="border:1px solid #ddd;border-radius:8px;overflow:hidden;">'
                f'<div style="background:#f0f0f0;padding:4px 12px;font-size:12px;color:#666;">'
                f'第 {i + 1} 页</div>'
                f'<img src="data:image/png;base64,{b64}" style="width:100%;display:block;" />'
                f'</div>'
            )
        html_parts.append("</div>")
        return "\n".join(html_parts)

    # 回退: 语义化 HTML
    return docx_to_html(docx_path)
