"""
PPT 图片自动匹配引擎

根据幻灯片标题/内容中的关键词，自动从 assets/images/ 中选择最相关的图片插入。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

# ── 图片 → 关键词映射 ──
# 每张图片对应一组关键词，匹配度越高越优先
IMAGE_KEYWORD_MAP = {
    # DNA复制相关
    "dna_replication_notes.jpg": ["DNA复制", "复制", "replication", "半保留", "复制叉", "冈崎片段", "解旋酶"],
    "dna_replication_diagram.jpg": ["DNA复制", "复制", "半保留复制", "双向复制", "前导链", "后随链", "DNA聚合酶"],
    "dna_replication_process.jpg": ["DNA复制", "复制过程", "半保留", "密度梯度离心", "同位素标记"],

    # 转录相关
    "transcription_textbook.jpg": ["转录", "mRNA", "RNA聚合酶", "中心法则", "DNA转录", "模板链"],
    "transcription_detail.jpg": ["转录", "transcription", "RNA聚合酶", "启动子", "终止子", "编码链", "模板链"],

    # 细胞结构相关
    "cell_structure_model.jpg": ["细胞结构", "细胞膜", "细胞器", "线粒体", "叶绿体", "内质网", "高尔基体", "模型"],
    "cell_structure_color.jpg": ["细胞结构", "植物细胞", "动物细胞", "细胞核", "核膜", "核仁", "对比"],
    "cell_organelle_detail.jpg": ["细胞器", "分工合作", "内质网", "高尔基体", "液泡", "叶绿体基质"],
    "cell_organisms.jpg": ["单细胞", "眼虫", "变形虫", "草履虫", "走近细胞"],

    # 思维导图
    "bio_mindmap_overview.jpg": ["分子与细胞", "必修一", "思维导图", "化合物", "细胞代谢", "光合作用", "呼吸作用", "ATP"],

    # 遗传进化
    "genetics_evolution_overview.jpg": ["遗传", "进化", "中心法则", "基因", "性状", "基因型", "表现型", "分离定律"],
    "genetics_mendel.jpg": ["孟德尔", "分离定律", "遗传", "显性", "隐性", "杂交", "豌豆", "自由组合"],

    # 基因突变
    "gene_mutation_mindmap.jpg": ["基因突变", "基因重组", "突变", "诱变育种", "癌变"],
    "mutation_sickle_cell.jpg": ["突变", "镰刀型", "血红蛋白", "碱基替换", "变异"],

    # 表观遗传/基因调控
    "epigenetics_diagram.jpg": ["表观遗传", "基因调控", "甲基化", "组蛋白", "epigenetics", "RNA修饰"],
}


def find_best_image(
    title: str,
    content_points: List[str],
    assets_dir: str = "assets/images",
    used_images: Optional[set] = None,
) -> Optional[str]:
    """
    根据幻灯片标题和内容要点，找到最匹配的图片。

    Args:
        title: 幻灯片标题
        content_points: 内容要点列表
        assets_dir: 图片目录
        used_images: 已使用的图片集合（避免重复）

    Returns:
        最匹配的图片路径，或 None
    """
    if used_images is None:
        used_images = set()

    # 合并所有文本用于匹配
    all_text = (title + " " + " ".join(content_points)).lower()

    best_score = 0
    best_image = None

    for filename, keywords in IMAGE_KEYWORD_MAP.items():
        if filename in used_images:
            continue

        img_path = Path(assets_dir) / filename
        if not img_path.exists():
            continue

        # 计算匹配分数
        score = sum(1 for kw in keywords if kw.lower() in all_text)

        if score > best_score:
            best_score = score
            best_image = filename

    if best_image and best_score >= 1:
        return str(Path(assets_dir) / best_image)

    return None


def get_all_topic_images(
    topic: str,
    assets_dir: str = "assets/images",
    max_images: int = 5,
) -> List[Tuple[str, str]]:
    """
    获取与主题最相关的所有图片（用于封面/概览页）。

    Returns:
        [(图片路径, 图片描述), ...]
    """
    results = []
    topic_lower = topic.lower()

    scored = []
    for filename, keywords in IMAGE_KEYWORD_MAP.items():
        img_path = Path(assets_dir) / filename
        if not img_path.exists():
            continue
        score = sum(1 for kw in keywords if kw.lower() in topic_lower)
        if score > 0:
            desc = "、".join(keywords[:3])
            scored.append((score, str(img_path), desc))

    scored.sort(key=lambda x: -x[0])
    return [(path, desc) for _, path, desc in scored[:max_images]]
