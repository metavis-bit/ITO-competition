/**
 * Scene Content Generation API
 *
 * Generates scene content (slides/quiz/interactive/pbl) from an outline.
 * This is the first half of the two-step scene generation pipeline.
 * Does NOT generate actions — use /api/generate/scene-actions for that.
 */

import { NextRequest } from 'next/server';
import { callLLM } from '@/lib/ai/llm';
import {
  applyOutlineFallbacks,
  generateSceneContent,
  buildVisionUserContent,
} from '@/lib/generation/generation-pipeline';
import type { AgentInfo } from '@/lib/generation/generation-pipeline';
import type { SceneOutline, PdfImage, ImageMapping, UserRequirements } from '@/lib/types/generation';
import { createLogger } from '@/lib/logger';
import { normalizeOutputTypes } from '@/lib/types/output-types';
import type { OutputArtifactType } from '@/lib/types/output-types';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { resolveModelFromHeaders } from '@/lib/server/resolve-model';
import {
  isBackendEnabled,
  proxyJsonPost,
  type BackendGenerateRequest,
  type BackendGenerateResponse,
} from '@/lib/server/backend-proxy';

const log = createLogger('Scene Content API');

export const maxDuration = 300;
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

const BIOLOGY_REFERENCE_SCOPE =
  '高中生物《分子与细胞》《遗传与进化》, 重点涵盖中心法则、DNA复制、转录、翻译、减数分裂。';
const BIOLOGY_REFERENCE_MEDIA = '教材PDF、专题讲义、答案解析、教学视频。';

const GAME_REQUEST_RE = /(互动|游戏|测验|quiz|闯关|练习)/i;
const ANIMATION_REQUEST_RE = /(动画|概念动画|过程动画|animation|演示过程)/i;

function collectArtifactTypes(
  artifacts: Array<{ type?: string }> | undefined,
): Set<string> {
  const types = new Set<string>();
  for (const artifact of artifacts || []) {
    const type = (artifact?.type || '').trim();
    if (!type) continue;
    types.add(type);
  }
  return types;
}

function mergeArtifactsByType<
  T extends {
    type: string;
  },
>(base: T[], next: T[]): T[] {
  const merged = new Map<string, T>();
  for (const artifact of base) {
    merged.set(artifact.type, artifact);
  }
  for (const artifact of next) {
    merged.set(artifact.type, artifact);
  }
  return Array.from(merged.values());
}

function describeMissingArtifact(type: OutputArtifactType): string {
  switch (type) {
    case 'pptx':
      return '课件 PPT 未生成';
    case 'docx':
      return '教案 DOCX 未生成';
    case 'game_html':
      return '互动游戏未生成';
    case 'animation_html':
      return '概念动画未生成';
    default:
      return `${type} 未生成`;
  }
}

function isTimeoutLikeMessage(message: string): boolean {
  const normalized = (message || '').toLowerCase();
  return (
    normalized.includes('timed out') ||
    normalized.includes('timeout') ||
    normalized.includes('planning failed')
  );
}

function shouldRequireOptionalArtifact(params: {
  type: OutputArtifactType;
  outline?: SceneOutline;
  requirementText: string;
}): boolean {
  const corpus = [
    params.requirementText,
    params.outline?.title,
    params.outline?.description,
    ...(params.outline?.keyPoints || []),
  ]
    .filter(Boolean)
    .join('\n');

  if (params.type === 'game_html') {
    return GAME_REQUEST_RE.test(corpus);
  }
  if (params.type === 'animation_html') {
    return ANIMATION_REQUEST_RE.test(corpus);
  }
  return false;
}

function deriveKeyFocus(outline: SceneOutline, requirementText: string): string[] {
  const fromOutline = Array.isArray(outline.keyPoints) ? outline.keyPoints : [];
  const fromRequirement = requirementText
    .split(/[，,。；;、\n]/)
    .map((item) => item.trim())
    .filter((item) => item.length >= 2 && item.length <= 24)
    .slice(0, 6);

  const matchedBiologyTerms = BIOLOGY_KEY_TERMS.filter((term) => requirementText.includes(term));
  const seedTerms = matchedBiologyTerms.length > 0 ? matchedBiologyTerms : BIOLOGY_KEY_TERMS.slice(0, 4);

  return dedupeStrings([...seedTerms, ...fromOutline, ...fromRequirement]).slice(0, 8);
}

function buildBackendSpecialRequirements(params: {
  requirements?: UserRequirements;
  stageInfo?: { style?: string };
}): string | undefined {
  const { requirements, stageInfo } = params;
  const lines: string[] = [
    '系统目标: 减负增效，教师聚焦教学设计与内容质量。',
    '生成偏好: 在保证准确性的前提下强化可视化表达与课堂互动创新。',
    '学科约束: 当前知识库限定为高中生物。',
    `知识库范围: ${BIOLOGY_REFERENCE_SCOPE}`,
    `知识载体: ${BIOLOGY_REFERENCE_MEDIA}`,
    '生成要求: 优先融合上传参考资料中的知识结构、题解逻辑和风格特征。',
  ];

  if (requirements?.userTeachingStyle?.trim()) {
    lines.push(`教师教学风格: ${requirements.userTeachingStyle.trim()}`);
  }
  if (stageInfo?.style?.trim()) {
    lines.push(`课堂呈现风格: ${stageInfo.style.trim()}`);
  }
  if (requirements?.userBio?.trim()) {
    lines.push(`教师个性化要求参考: ${requirements.userBio.trim()}`);
  }

  return lines.length > 0 ? lines.join('\n') : undefined;
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    // ── Backend proxy mode ──
    if (isBackendEnabled()) {
      const {
        outline: rawOutline,
        allOutlines,
        stageInfo,
        requirements,
        backendSessionId,
        backendReferenceIndex,
        backendReferenceIndexes,
        outputTypes,
      } = body as {
        outline?: SceneOutline;
        allOutlines?: SceneOutline[];
        stageInfo?: { name: string; language?: string; description?: string; style?: string };
        requirements?: UserRequirements;
        backendSessionId?: string;
        backendReferenceIndex?: string;
        backendReferenceIndexes?: string[];
        outputTypes?: string[];
      };

      if (!rawOutline) {
        return apiError('MISSING_REQUIRED_FIELD', 400, 'outline is required');
      }

      const indexes = Array.from(
        new Set(
          ['kb', ...(backendReferenceIndexes || []), backendReferenceIndex].filter(
            (v): v is string => !!v,
          ),
        ),
      );

      const normalizedOutputTypes = normalizeOutputTypes(outputTypes);
      const requirementText = (requirements?.requirement || '').trim();
      const sceneCount = Array.isArray(allOutlines) && allOutlines.length > 0 ? allOutlines.length : 12;
      const pageRange = `1-${Math.max(1, sceneCount)}`;
      const keyFocus = deriveKeyFocus(rawOutline, requirementText);
      const targetAudience = (requirements?.userGradeLevel || '').trim();
      const teachingGoal = [rawOutline.description, stageInfo?.description]
        .map((v) => (v || '').trim())
        .filter(Boolean)
        .join('；');
      const topic = (rawOutline.title || stageInfo?.name || '智绘生物').trim();
      const specialRequirements = buildBackendSpecialRequirements({ requirements, stageInfo });

      const backendBody: BackendGenerateRequest = {
        session_id: backendSessionId,
        topic,
        subject: '生物',
        target_audience: targetAudience,
        grade_level: targetAudience,
        teaching_goal:
          teachingGoal || requirementText.slice(0, 160) || '基于高中生物核心概念进行教学设计',
        page_range: pageRange,
        key_focus: keyFocus,
        indexes,
        output_types: normalizedOutputTypes,
        special_requirements: specialRequirements,
      };

      try {
        const result = await proxyJsonPost<BackendGenerateResponse>(
          '/v1/courseware/generate',
          backendBody,
          { signal: req.signal, timeout: 300_000 },
        );

        const baseRequiredTypes = normalizedOutputTypes.filter((t) => t === 'pptx' || t === 'docx');
        const optionalTypes = normalizedOutputTypes.filter((t) => t !== 'pptx' && t !== 'docx');
        const promotedOptionalTypes = optionalTypes.filter((type) =>
          shouldRequireOptionalArtifact({
            type,
            outline: rawOutline,
            requirementText,
          }),
        );
        const mustHaveTypes = Array.from(new Set([...baseRequiredTypes, ...promotedOptionalTypes]));

        let artifacts = Array.isArray(result.artifacts) ? result.artifacts : [];
        let errors = Array.isArray(result.errors) ? [...result.errors] : [];
        let artifactTypes = collectArtifactTypes(artifacts);
        let missingMustHave = mustHaveTypes.filter((t) => !artifactTypes.has(t));

        if (missingMustHave.length > 0) {
          log.warn(
            `Missing required artifacts after first backend call: ${missingMustHave.join(', ')}; retrying once`,
          );
          try {
            const retryResult = await proxyJsonPost<BackendGenerateResponse>(
              '/v1/courseware/generate',
              {
                ...backendBody,
                session_id: result.session_id || backendBody.session_id,
                output_types: missingMustHave,
              },
              { signal: req.signal, timeout: 300_000 },
            );
            artifacts = mergeArtifactsByType(
              artifacts,
              Array.isArray(retryResult.artifacts) ? retryResult.artifacts : [],
            );
            errors = [...errors, ...(Array.isArray(retryResult.errors) ? retryResult.errors : [])];
            artifactTypes = collectArtifactTypes(artifacts);
            missingMustHave = mustHaveTypes.filter((t) => !artifactTypes.has(t));
          } catch (retryErr) {
            errors.push(
              retryErr instanceof Error ? retryErr.message : 'Retry failed for required artifacts',
            );
          }
        }

        const missingOptional = optionalTypes.filter(
          (t) => !artifactTypes.has(t) && !promotedOptionalTypes.includes(t),
        );
        if (missingOptional.length > 0) {
          log.warn(`Optional artifacts missing: ${missingOptional.join(', ')}`);
        }

        const missingArtifactErrors = [
          ...missingMustHave.map(describeMissingArtifact),
          ...missingOptional.map(describeMissingArtifact),
        ];
        if (missingArtifactErrors.length > 0) {
          errors = [...errors, ...missingArtifactErrors];
        }

        if (missingMustHave.length > 0) {
          const errorSuffix = errors.length > 0 ? `; errors=${errors.join(' | ')}` : '';
          return apiError(
            'GENERATION_FAILED',
            502,
            `Required artifacts not generated: ${missingMustHave.join(', ')}${errorSuffix}`,
          );
        }

        // Map backend result back to OpenMaic format
        const content = {
          sessionId: result.session_id,
          versionId: result.version_id,
          artifacts,
          plan: result.plan,
          errors,
          requestedOutputTypes: normalizedOutputTypes,
          missingArtifacts: {
            required: missingMustHave,
            optional: missingOptional,
          },
        };

        const effectiveOutline: SceneOutline = {
          ...rawOutline,
          language:
            rawOutline.language || (stageInfo?.language as 'zh-CN' | 'en-US') || 'zh-CN',
        };

        return apiSuccess({ content, effectiveOutline });
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Backend proxy error';
        log.error('Backend proxy error:', msg);
        if (isTimeoutLikeMessage(msg)) {
          return apiError('GENERATION_TIMEOUT', 504, msg);
        }
        return apiError('GENERATION_FAILED', 500, msg);
      }
    }
    const {
      outline: rawOutline,
      allOutlines,
      pdfImages,
      imageMapping,
      stageInfo,
      stageId,
      agents,
    } = body as {
      outline: SceneOutline;
      allOutlines: SceneOutline[];
      pdfImages?: PdfImage[];
      imageMapping?: ImageMapping;
      stageInfo: {
        name: string;
        description?: string;
        language?: string;
        style?: string;
      };
      stageId: string;
      agents?: AgentInfo[];
    };

    // Validate required fields
    if (!rawOutline) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'outline is required');
    }
    if (!allOutlines || allOutlines.length === 0) {
      return apiError(
        'MISSING_REQUIRED_FIELD',
        400,
        'allOutlines is required and must not be empty',
      );
    }
    if (!stageId) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'stageId is required');
    }

    // Ensure outline has language from stageInfo (fallback for older outlines)
    const outline: SceneOutline = {
      ...rawOutline,
      language: rawOutline.language || (stageInfo?.language as 'zh-CN' | 'en-US') || 'zh-CN',
    };

    // ── Model resolution from request headers ──
    const { model: languageModel, modelInfo, modelString } = resolveModelFromHeaders(req);

    // Detect vision capability
    const hasVision = !!modelInfo?.capabilities?.vision;

    // Vision-aware AI call function
    const aiCall = async (
      systemPrompt: string,
      userPrompt: string,
      images?: Array<{ id: string; src: string }>,
    ): Promise<string> => {
      if (images?.length && hasVision) {
        const result = await callLLM(
          {
            model: languageModel,
            system: systemPrompt,
            messages: [
              {
                role: 'user' as const,
                content: buildVisionUserContent(userPrompt, images),
              },
            ],
            maxOutputTokens: modelInfo?.outputWindow,
          },
          'scene-content',
        );
        return result.text;
      }
      const result = await callLLM(
        {
          model: languageModel,
          system: systemPrompt,
          prompt: userPrompt,
          maxOutputTokens: modelInfo?.outputWindow,
        },
        'scene-content',
      );
      return result.text;
    };

    // ── Apply fallbacks ──
    const effectiveOutline = applyOutlineFallbacks(outline, !!languageModel);

    // ── Filter images assigned to this outline ──
    let assignedImages: PdfImage[] | undefined;
    if (
      pdfImages &&
      pdfImages.length > 0 &&
      effectiveOutline.suggestedImageIds &&
      effectiveOutline.suggestedImageIds.length > 0
    ) {
      const suggestedIds = new Set(effectiveOutline.suggestedImageIds);
      assignedImages = pdfImages.filter((img) => suggestedIds.has(img.id));
    }

    // ── Media generation is handled client-side in parallel (media-orchestrator.ts) ──
    // The content generator receives placeholder IDs (gen_img_1, gen_vid_1) as-is.
    // resolveImageIds() in generation-pipeline.ts will keep these placeholders in elements.
    const generatedMediaMapping: ImageMapping = {};

    // ── Generate content ──
    log.info(
      `Generating content: "${effectiveOutline.title}" (${effectiveOutline.type}) [model=${modelString}]`,
    );

    const content = await generateSceneContent(
      effectiveOutline,
      aiCall,
      assignedImages,
      imageMapping,
      effectiveOutline.type === 'pbl' ? languageModel : undefined,
      hasVision,
      generatedMediaMapping,
      agents,
    );

    if (!content) {
      log.error(`Failed to generate content for: "${effectiveOutline.title}"`);

      return apiError(
        'GENERATION_FAILED',
        500,
        `Failed to generate content: ${effectiveOutline.title}`,
      );
    }

    log.info(`Content generated successfully: "${effectiveOutline.title}"`);

    return apiSuccess({ content, effectiveOutline });
  } catch (error) {
    log.error('Scene content generation error:', error);
    return apiError('INTERNAL_ERROR', 500, error instanceof Error ? error.message : String(error));
  }
}







