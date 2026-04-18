import { NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { isBackendEnabled, proxyJsonPost, type BackendGenerateRequest } from '@/lib/server/backend-proxy';
import { normalizeOutputTypes } from '@/lib/types/output-types';
import type { UserRequirements } from '@/lib/types/generation';

function dedupeStrings(values: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of values) {
    const value = (raw || '').trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

const BIOLOGY_KEY_TERMS = [
  '分子与细胞',
  '遗传与进化',
  '中心法则',
  'DNA复制',
  '转录',
  '翻译',
  '减数分裂',
] as const;

function deriveKeyFocus(requirementText: string): string[] {
  const matchedBiologyTerms = BIOLOGY_KEY_TERMS.filter((term) => requirementText.includes(term));
  const fromRequirement = requirementText
    .split(/[，,。；;、\n]/)
    .map((item) => item.trim())
    .filter((item) => item.length >= 2 && item.length <= 24)
    .slice(0, 6);
  const seedTerms = matchedBiologyTerms.length > 0 ? matchedBiologyTerms : BIOLOGY_KEY_TERMS.slice(0, 4);
  return dedupeStrings([...seedTerms, ...fromRequirement]).slice(0, 8);
}

function parsePageRange(requirementText: string, fallback = '6-8'): string {
  const rangeMatch = requirementText.match(/(\d{1,2})\s*[-~～到至]\s*(\d{1,2})\s*(?:页|p|slides?)/i);
  if (rangeMatch) {
    const start = Number(rangeMatch[1]);
    const end = Number(rangeMatch[2]);
    if (Number.isFinite(start) && Number.isFinite(end)) {
      const min = Math.max(1, Math.min(start, end));
      const max = Math.max(start, end);
      return `${min}-${max}`;
    }
  }
  const singleMatch = requirementText.match(/(?:约|大约|around|about)?\s*(\d{1,2})\s*(?:页|p|slides?)/i);
  if (singleMatch) {
    const pages = Number(singleMatch[1]);
    if (Number.isFinite(pages) && pages > 0) {
      const min = Math.max(1, pages - 1);
      const max = Math.max(min + 1, pages + 1);
      return `${min}-${max}`;
    }
  }
  return fallback;
}

function buildBackendSpecialRequirements(requirements: UserRequirements): string | undefined {
  const lines: string[] = [
    '系统目标: 减负增效，教师聚焦教学设计与内容质量。',
    '生成偏好: 答辩演示稳定优先，先保证结构完整和产物可展示。',
    '学科约束: 当前知识库限定为高中生物。',
  ];

  if (requirements.userTeachingStyle?.trim()) {
    lines.push(`教师教学风格: ${requirements.userTeachingStyle.trim()}`);
  }
  if (requirements.userBio?.trim()) {
    lines.push(`教师个性化要求参考: ${requirements.userBio.trim()}`);
  }

  return lines.join('\n');
}

export async function POST(req: NextRequest) {
  if (!isBackendEnabled()) {
    return apiError('INTERNAL_ERROR', 501, 'Backend not enabled');
  }

  try {
    const body = await req.json();
    const {
      requirements,
      backendSessionId,
      backendReferenceIndex,
      backendReferenceIndexes,
      outputTypes,
    } = body as {
      requirements?: UserRequirements;
      backendSessionId?: string;
      backendReferenceIndex?: string;
      backendReferenceIndexes?: string[];
      outputTypes?: string[];
    };

    if (!requirements) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'requirements is required');
    }

    const indexes = Array.from(
      new Set(
        ['kb', ...(backendReferenceIndexes || []), backendReferenceIndex].filter(
          (value): value is string => !!value,
        ),
      ),
    );
    const normalizedOutputTypes = normalizeOutputTypes(outputTypes);
    const requirementText = (requirements.requirement || '').trim();

    const backendBody: BackendGenerateRequest = {
      session_id: backendSessionId,
      topic: requirementText || '智绘生物',
      subject: '生物',
      target_audience: (requirements.userGradeLevel || '').trim(),
      grade_level: (requirements.userGradeLevel || '').trim(),
      teaching_goal: requirementText.slice(0, 180) || '围绕高中生物核心概念完成课堂教学设计',
      page_range: parsePageRange(requirementText),
      key_focus: deriveKeyFocus(requirementText),
      indexes,
      output_types: normalizedOutputTypes,
      special_requirements: buildBackendSpecialRequirements(requirements),
    };

    const result = await proxyJsonPost('/v1/jobs/courseware', backendBody, {
      signal: req.signal,
      timeout: 30_000,
    }) as Record<string, unknown>;
    return apiSuccess({
      jobId: result.job_id,
      status: result.status,
      stage: result.stage,
      progress: result.progress,
      sessionId: result.session_id,
      versionId: result.version_id,
    });
  } catch (err) {
    return apiError('UPSTREAM_ERROR', 500, err instanceof Error ? err.message : 'Job create failed');
  }
}
