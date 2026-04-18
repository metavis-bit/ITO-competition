/**
 * Biology image keyword matching for slide generation.
 * Mirrors backend/src/rag/image_matcher.py logic.
 * Images served from backend at /v1/assets/images/
 */

export const BIOLOGY_IMAGE_KEYWORDS: Record<string, string[]> = {
  'dna_replication_notes.jpg': ['DNA复制', '复制', '半保留', '复制叉', '冈崎片段', '解旋酶'],
  'dna_replication_diagram.jpg': ['DNA复制', '半保留复制', '双向复制', '前导链', '后随链', 'DNA聚合酶'],
  'dna_replication_process.jpg': ['DNA复制', '复制过程', '半保留', '密度梯度离心'],
  'transcription_textbook.jpg': ['转录', 'mRNA', 'RNA聚合酶', '中心法则', '模板链'],
  'transcription_detail.jpg': ['转录', 'RNA聚合酶', '启动子', '终止子', '编码链'],
  'cell_structure_model.jpg': ['细胞结构', '细胞膜', '细胞器', '线粒体', '叶绿体', '内质网'],
  'cell_structure_color.jpg': ['细胞结构', '植物细胞', '动物细胞', '细胞核', '核膜'],
  'cell_organelle_detail.jpg': ['细胞器', '分工合作', '内质网', '高尔基体', '液泡'],
  'cell_organisms.jpg': ['单细胞', '眼虫', '变形虫', '草履虫'],
  'bio_mindmap_overview.jpg': ['分子与细胞', '思维导图', '化合物', '细胞代谢', '光合作用'],
  'genetics_evolution_overview.jpg': ['遗传', '进化', '中心法则', '基因', '分离定律'],
  'genetics_mendel.jpg': ['孟德尔', '分离定律', '显性', '隐性', '杂交', '豌豆'],
  'gene_mutation_mindmap.jpg': ['基因突变', '基因重组', '突变', '诱变育种', '癌变'],
  'mutation_sickle_cell.jpg': ['突变', '镰刀型', '血红蛋白', '碱基替换', '变异'],
  'epigenetics_diagram.jpg': ['表观遗传', '基因调控', '甲基化', '组蛋白'],
};

const usedImages = new Set<string>();

export function resetUsedImages() {
  usedImages.clear();
}

/**
 * Find the best matching biology image for a given slide title/description.
 * Returns the filename or null if no match found.
 */
export function matchBiologyImage(title: string, description?: string): string | null {
  const text = `${title} ${description || ''}`.toLowerCase();
  let bestScore = 0;
  let bestFile: string | null = null;

  for (const [filename, keywords] of Object.entries(BIOLOGY_IMAGE_KEYWORDS)) {
    if (usedImages.has(filename)) continue;
    const score = keywords.filter((kw) => text.includes(kw.toLowerCase())).length;
    if (score > bestScore) {
      bestScore = score;
      bestFile = filename;
    }
  }

  if (bestFile && bestScore >= 1) {
    usedImages.add(bestFile);
    return bestFile;
  }
  return null;
}

/** Get the URL for a biology image filename (proxied through Next.js rewrite) */
export function getBiologyImageUrl(filename: string): string {
  return `/v1/assets/images/${filename}`;
}
