/**
 * Scene Outlines Streaming API (SSE)
 *
 * Streams outline generation via Server-Sent Events.
 * Emits individual outline objects as they're parsed from the LLM response,
 * so the frontend can display them incrementally.
 *
 * SSE events:
 *   { type: 'outline', data: SceneOutline, index: number }
 *   { type: 'done', outlines: SceneOutline[] }
 *   { type: 'error', error: string }
 */

import { NextRequest } from 'next/server';
import { streamLLM } from '@/lib/ai/llm';
import { buildPrompt, PROMPT_IDS } from '@/lib/generation/prompts';
import {
  formatImageDescription,
  formatImagePlaceholder,
  buildVisionUserContent,
  uniquifyMediaElementIds,
  formatTeacherPersonaForPrompt,
} from '@/lib/generation/generation-pipeline';
import type { AgentInfo } from '@/lib/generation/generation-pipeline';
import { MAX_PDF_CONTENT_CHARS, MAX_VISION_IMAGES } from '@/lib/constants/generation';
import { nanoid } from 'nanoid';
import type {
  UserRequirements,
  PdfImage,
  SceneOutline,
  ImageMapping,
} from '@/lib/types/generation';
import { apiError } from '@/lib/server/api-response';
import { createLogger } from '@/lib/logger';
import { resolveModelFromHeaders } from '@/lib/server/resolve-model';
import {
  isBackendEnabled,
  proxyStreamPost,
  type BackendSSEEvent,
  type BackendStreamRequest,
} from '@/lib/server/backend-proxy';
const log = createLogger('Outlines Stream');

export const maxDuration = 300;

/**
 * Incremental JSON array parser.
 * Extracts complete top-level objects from a partially-streamed JSON array.
 * Returns newly found objects (skipping `alreadyParsed` count).
 */
function extractNewOutlines(buffer: string, alreadyParsed: number): SceneOutline[] {
  const results: SceneOutline[] = [];

  // Find the start of the JSON array (skip any markdown fencing)
  const stripped = buffer.replace(/^[\s\S]*?(?=\[)/, '');
  const arrayStart = stripped.indexOf('[');
  if (arrayStart === -1) return results;

  let depth = 0;
  let objectStart = -1;
  let inString = false;
  let escaped = false;
  let objectCount = 0;

  for (let i = arrayStart + 1; i < stripped.length; i++) {
    const char = stripped[i];

    if (escaped) {
      escaped = false;
      continue;
    }
    if (char === '\\' && inString) {
      escaped = true;
      continue;
    }
    if (char === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;

    if (char === '{') {
      if (depth === 0) objectStart = i;
      depth++;
    } else if (char === '}') {
      depth--;
      if (depth === 0 && objectStart >= 0) {
        objectCount++;
        if (objectCount > alreadyParsed) {
          try {
            const obj = JSON.parse(stripped.substring(objectStart, i + 1));
            results.push(obj);
          } catch {
            // Incomplete or invalid JSON — skip
          }
        }
        objectStart = -1;
      }
    }
  }

  return results;
}

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

const BIOLOGY_FOCUS_ALIASES: Array<{ term: string; aliases: string[] }> = [
  { term: '分子与细胞', aliases: ['分子与细胞', 'molecules and cells'] },
  { term: '遗传与进化', aliases: ['遗传与进化', 'genetics and evolution'] },
  { term: '中心法则', aliases: ['中心法则', 'central dogma'] },
  { term: 'DNA复制', aliases: ['DNA复制', 'dna复制', 'dna replication'] },
  { term: '转录', aliases: ['转录', 'transcription'] },
  { term: '翻译', aliases: ['翻译', 'translation'] },
  { term: '减数分裂', aliases: ['减数分裂', 'meiosis'] },
];

const BIOLOGY_REFERENCE_SCOPE =
  '高中生物《分子与细胞》《遗传与进化》, 重点涵盖中心法则、DNA复制、转录、翻译、减数分裂。';
const BIOLOGY_REFERENCE_MEDIA = '教材PDF、专题讲义、答案解析、教学视频。';

function extractBiologyFocus(requirement: string): string[] {
  const text = (requirement || '').trim();
  const lower = text.toLowerCase();

  const matched = BIOLOGY_FOCUS_ALIASES.filter(({ aliases }) =>
    aliases.some((alias) => lower.includes(alias.toLowerCase())),
  ).map(({ term }) => term);

  if (matched.length === 0) {
    return ['分子与细胞', '遗传与进化', '中心法则', 'DNA复制', '转录', '翻译'];
  }

  return dedupeStrings(matched).slice(0, 6);
}

function parsePageRange(requirement: string, fallback = '10-15'): string {
  const rangeMatch = requirement.match(/(\d{1,2})\s*[-~～到至]\s*(\d{1,2})\s*(?:页|p|slides?)/i);
  if (rangeMatch) {
    const start = Number(rangeMatch[1]);
    const end = Number(rangeMatch[2]);
    if (Number.isFinite(start) && Number.isFinite(end)) {
      const min = Math.max(1, Math.min(start, end));
      const max = Math.max(start, end);
      return `${min}-${max}`;
    }
  }

  const singleMatch = requirement.match(/(?:约|大约|around|about)?\s*(\d{1,2})\s*(?:页|p|slides?)/i);
  if (singleMatch) {
    const pages = Number(singleMatch[1]);
    if (Number.isFinite(pages) && pages > 0) {
      const min = Math.max(1, pages - 2);
      const max = Math.max(min + 1, pages + 2);
      return `${min}-${max}`;
    }
  }

  return fallback;
}

function buildTeacherProfilePrompt(requirements: UserRequirements): string {
  const lines: string[] = [];
  if (requirements.userNickname?.trim()) {
    lines.push(`Teacher Name: ${requirements.userNickname.trim()}`);
  }
  const rawSubject = requirements.userSubject?.trim() || '';
  const normalizedSubject = rawSubject.includes('生物') ? rawSubject : '生物';
  lines.push(`Subject: ${normalizedSubject}`);
  if (requirements.userGradeLevel?.trim()) {
    lines.push(`Target Grade: ${requirements.userGradeLevel.trim()}`);
  }
  if (requirements.userTeachingStyle?.trim()) {
    lines.push(`Teaching Style: ${requirements.userTeachingStyle.trim()}`);
  }
  if (requirements.userBio?.trim()) {
    lines.push(`Profile Notes: ${requirements.userBio.trim()}`);
  }

  if (lines.length === 0) {
    return '';
  }

  const title = requirements.language === 'zh-CN' ? '## 教师画像' : '## Teacher Profile';
  const guidance =
    requirements.language === 'zh-CN'
      ? '请将以上教师画像用于内容深度、互动方式和讲解语气的个性化适配。'
      : 'Use this teacher profile to personalize depth, interactions, and teaching tone.';

  return `${title}\n\n${lines.join('\n')}\n\n${guidance}\n\n---`;
}

function buildBackendSpecialRequirements(requirements: UserRequirements): string | undefined {
  const lines: string[] = [
    '系统目标: 减负增效，教师聚焦教学设计与内容质量。',
    '学科约束: 当前知识库限定为高中生物。',
    `知识库范围: ${BIOLOGY_REFERENCE_SCOPE}`,
    `知识载体: ${BIOLOGY_REFERENCE_MEDIA}`,
    '生成要求: 优先利用上传参考资料中的知识结构、案例内容和表达风格。',
  ];

  if (requirements.userTeachingStyle?.trim()) {
    lines.push(`教师教学风格: ${requirements.userTeachingStyle.trim()}`);
  }
  if (requirements.userBio?.trim()) {
    lines.push(`教师个性化要求参考: ${requirements.userBio.trim()}`);
  }

  return lines.length > 0 ? lines.join('\n') : undefined;
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    // ── Backend proxy mode ──
    if (isBackendEnabled()) {
      const { requirements, backendSessionId, backendReferenceIndex, backendReferenceIndexes } = body as {
        requirements?: UserRequirements;
        backendSessionId?: string;
        backendReferenceIndex?: string;
        backendReferenceIndexes?: string[];
      };
      if (!requirements) {
        return apiError('MISSING_REQUIRED_FIELD', 400, 'Requirements are required');
      }

      const indexes = Array.from(
        new Set(
          ['kb', ...(backendReferenceIndexes || []), backendReferenceIndex].filter(
            (v): v is string => !!v,
          ),
        ),
      );

      const requirementText = (requirements.requirement || '').trim();
      const topic = requirementText || '智绘生物';
      const targetAudience = (requirements.userGradeLevel || '').trim();
      const keyFocus = extractBiologyFocus(requirementText);

      const backendBody: BackendStreamRequest = {
        session_id: backendSessionId,
        topic,
        subject: '生物',
        target_audience: targetAudience,
        teaching_goal: requirementText.slice(0, 180) || '围绕高中生物核心概念完成课堂教学设计',
        grade_level: targetAudience,
        page_range: parsePageRange(requirementText),
        key_focus: keyFocus,
        special_requirements: buildBackendSpecialRequirements(requirements),
        indexes,
      };

      const collectedOutlines: SceneOutline[] = [];

      const stream = proxyStreamPost('/v1/outline/stream', backendBody, {
        signal: req.signal,
        transformEvent: (event: BackendSSEEvent) => {
          if (event.event === 'OUTLINE_DONE') {
            const plan = (event.data.plan || {}) as {
              slides?: Array<Record<string, unknown>>;
            };
            const slides = Array.isArray(plan.slides) ? plan.slides : [];

            collectedOutlines.length = 0;
            slides.forEach((slide, idx) => {
              const outline: SceneOutline = {
                id: nanoid(),
                order: idx + 1,
                title: String(slide.title || ''),
                type: slide.layout === 'interactive' ? 'interactive' : 'slide',
                description: String(slide.notes || ''),
                keyPoints: Array.isArray(slide.keyPoints) ? slide.keyPoints.map(String) : [],
                language: (requirements.language as 'zh-CN' | 'en-US') || 'zh-CN',
              };
              collectedOutlines.push(outline);
            });

            return JSON.stringify({ type: 'done', outlines: collectedOutlines });
          }

          if (event.event === 'PIPELINE_DONE' && collectedOutlines.length > 0) {
            return JSON.stringify({ type: 'done', outlines: collectedOutlines });
          }

          if (event.event === 'ERROR' || event.event === 'error') {
            return JSON.stringify({
              type: 'error',
              error: String(event.data.error || 'Backend error'),
            });
          }

          // Ignore OUTLINE_CHUNK in backend mode because backend streams raw JSON text chunks.
          return null;
        },
      });

      return new Response(stream, {
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
        },
      });
    }
    // Get API configuration from request headers
    const { model: languageModel, modelInfo, modelString } = resolveModelFromHeaders(req);

    if (!body.requirements) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'Requirements are required');
    }

    const { requirements, pdfText, pdfImages, imageMapping, researchContext, agents } = body as {
      requirements: UserRequirements;
      pdfText?: string;
      pdfImages?: PdfImage[];
      imageMapping?: ImageMapping;
      researchContext?: string;
      agents?: AgentInfo[];
    };

    // Detect vision capability
    const hasVision = !!modelInfo?.capabilities?.vision;

    // Build prompt (same logic as generateSceneOutlinesFromRequirements)
    let availableImagesText =
      requirements.language === 'zh-CN' ? '无可用图片' : 'No images available';
    let visionImages: Array<{ id: string; src: string }> | undefined;

    if (pdfImages && pdfImages.length > 0) {
      if (hasVision && imageMapping) {
        // Vision mode: split into vision images (first N) and text-only (rest)
        const allWithSrc = pdfImages.filter((img) => imageMapping[img.id]);
        const visionSlice = allWithSrc.slice(0, MAX_VISION_IMAGES);
        const textOnlySlice = allWithSrc.slice(MAX_VISION_IMAGES);
        const noSrcImages = pdfImages.filter((img) => !imageMapping[img.id]);

        const visionDescriptions = visionSlice.map((img) =>
          formatImagePlaceholder(img, requirements.language),
        );
        const textDescriptions = [...textOnlySlice, ...noSrcImages].map((img) =>
          formatImageDescription(img, requirements.language),
        );
        availableImagesText = [...visionDescriptions, ...textDescriptions].join('\n');

        visionImages = visionSlice.map((img) => ({
          id: img.id,
          src: imageMapping[img.id],
          width: img.width,
          height: img.height,
        }));
      } else {
        // Text-only mode: full descriptions
        availableImagesText = pdfImages
          .map((img) => formatImageDescription(img, requirements.language))
          .join('\n');
      }
    }

    // Build media generation policy based on enabled flags
    const imageGenerationEnabled = req.headers.get('x-image-generation-enabled') === 'true';
    const videoGenerationEnabled = req.headers.get('x-video-generation-enabled') === 'true';
    let mediaGenerationPolicy = '';
    if (!imageGenerationEnabled && !videoGenerationEnabled) {
      mediaGenerationPolicy =
        '**IMPORTANT: Do NOT include any mediaGenerations in the outlines. Both image and video generation are disabled.**';
    } else if (!imageGenerationEnabled) {
      mediaGenerationPolicy =
        '**IMPORTANT: Do NOT include any image mediaGenerations (type: "image") in the outlines. Image generation is disabled. Video generation is allowed.**';
    } else if (!videoGenerationEnabled) {
      mediaGenerationPolicy =
        '**IMPORTANT: Do NOT include any video mediaGenerations (type: "video") in the outlines. Video generation is disabled. Image generation is allowed.**';
    }

    // Build teacher context and profile for personalization
    const teacherContext = formatTeacherPersonaForPrompt(agents);
    const userProfile = buildTeacherProfilePrompt(requirements);

    const prompts = buildPrompt(PROMPT_IDS.REQUIREMENTS_TO_OUTLINES, {
      requirement: requirements.requirement,
      language: requirements.language,
      pdfContent: pdfText
        ? pdfText.substring(0, MAX_PDF_CONTENT_CHARS)
        : requirements.language === 'zh-CN'
          ? '无'
          : 'None',
      availableImages: availableImagesText,
      userProfile,
      researchContext: researchContext || (requirements.language === 'zh-CN' ? '无' : 'None'),
      mediaGenerationPolicy,
      teacherContext,
    });

    if (!prompts) {
      return apiError('INTERNAL_ERROR', 500, 'Prompt template not found');
    }

    log.info(
      `Generating outlines: "${requirements.requirement.substring(0, 50)}" [model=${modelString}]`,
    );

    // Create SSE stream with heartbeat to prevent connection timeout
    const encoder = new TextEncoder();
    const HEARTBEAT_INTERVAL_MS = 15_000;
    const stream = new ReadableStream({
      async start(controller) {
        // Heartbeat: periodically send SSE comments to keep the connection alive.
        let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
        const startHeartbeat = () => {
          stopHeartbeat();
          heartbeatTimer = setInterval(() => {
            try {
              controller.enqueue(encoder.encode(`:heartbeat\n\n`));
            } catch {
              stopHeartbeat();
            }
          }, HEARTBEAT_INTERVAL_MS);
        };
        const stopHeartbeat = () => {
          if (heartbeatTimer) {
            clearInterval(heartbeatTimer);
            heartbeatTimer = null;
          }
        };

        const MAX_STREAM_RETRIES = 2;

        try {
          startHeartbeat();

          const streamParams = visionImages?.length
            ? {
                model: languageModel,
                system: prompts.system,
                messages: [
                  {
                    role: 'user' as const,
                    content: buildVisionUserContent(prompts.user, visionImages),
                  },
                ],
                maxOutputTokens: modelInfo?.outputWindow,
              }
            : {
                model: languageModel,
                system: prompts.system,
                prompt: prompts.user,
                maxOutputTokens: modelInfo?.outputWindow,
              };

          let parsedOutlines: SceneOutline[] = [];
          let lastError: string | undefined;

          for (let attempt = 1; attempt <= MAX_STREAM_RETRIES + 1; attempt++) {
            try {
              const result = streamLLM(streamParams, 'scene-outlines-stream');

              let fullText = '';
              parsedOutlines = [];

              for await (const chunk of result.textStream) {
                fullText += chunk;

                // Try to extract new outlines from the accumulated text
                const newOutlines = extractNewOutlines(fullText, parsedOutlines.length);
                for (const outline of newOutlines) {
                  // Ensure ID and order
                  const enriched = {
                    ...outline,
                    id: outline.id || nanoid(),
                    order: parsedOutlines.length + 1,
                  };
                  parsedOutlines.push(enriched);

                  const event = JSON.stringify({
                    type: 'outline',
                    data: enriched,
                    index: parsedOutlines.length - 1,
                  });
                  controller.enqueue(encoder.encode(`data: ${event}\n\n`));
                }
              }

              // Validate: got outlines?
              if (parsedOutlines.length > 0) break;

              // Empty result — retry if we have attempts left
              lastError = fullText.trim()
                ? 'LLM response could not be parsed into outlines'
                : 'LLM returned empty response';

              if (attempt <= MAX_STREAM_RETRIES) {
                log.warn(
                  `Empty outlines (attempt ${attempt}/${MAX_STREAM_RETRIES + 1}), retrying...`,
                );
                // Notify client a retry is happening
                const retryEvent = JSON.stringify({
                  type: 'retry',
                  attempt,
                  maxAttempts: MAX_STREAM_RETRIES + 1,
                });
                controller.enqueue(encoder.encode(`data: ${retryEvent}\n\n`));
              }
            } catch (error) {
              lastError = error instanceof Error ? error.message : String(error);

              if (attempt <= MAX_STREAM_RETRIES) {
                log.warn(
                  `Stream error (attempt ${attempt}/${MAX_STREAM_RETRIES + 1}), retrying...`,
                  error,
                );
                const retryEvent = JSON.stringify({
                  type: 'retry',
                  attempt,
                  maxAttempts: MAX_STREAM_RETRIES + 1,
                });
                controller.enqueue(encoder.encode(`data: ${retryEvent}\n\n`));
                continue;
              }
            }
          }

          if (parsedOutlines.length > 0) {
            // Replace sequential gen_img_N/gen_vid_N with globally unique IDs
            const uniquifiedOutlines = uniquifyMediaElementIds(parsedOutlines);
            const finalOutlines =
              !hasVision && (pdfImages?.length || 0) > 0
                ? uniquifiedOutlines.map((outline) => ({
                    ...outline,
                    // Enforce multimodal gating for PDF-attached images:
                    // without vision, never decide to attach PDF images.
                    suggestedImageIds: [],
                  }))
                : uniquifiedOutlines;
            if (!hasVision && (pdfImages?.length || 0) > 0) {
              log.warn(
                'Vision is not available for outlines generation; cleared suggestedImageIds for all scenes.',
              );
            }
            // Send done event with all outlines
            const doneEvent = JSON.stringify({
              type: 'done',
              outlines: finalOutlines,
            });
            controller.enqueue(encoder.encode(`data: ${doneEvent}\n\n`));
          } else {
            // All retries exhausted, no outlines produced
            log.error(
              `Outline generation failed after ${MAX_STREAM_RETRIES + 1} attempts: ${lastError}`,
            );
            const errorEvent = JSON.stringify({
              type: 'error',
              error: lastError || 'Failed to generate outlines',
            });
            controller.enqueue(encoder.encode(`data: ${errorEvent}\n\n`));
          }
        } catch (error) {
          const errorEvent = JSON.stringify({
            type: 'error',
            error: error instanceof Error ? error.message : String(error),
          });
          controller.enqueue(encoder.encode(`data: ${errorEvent}\n\n`));
        } finally {
          stopHeartbeat();
          controller.close();
        }
      },
    });

    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
    });
  } catch (error) {
    log.error('Streaming error:', error);
    return apiError('INTERNAL_ERROR', 500, error instanceof Error ? error.message : String(error));
  }
}










