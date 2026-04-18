'use client';

import { useEffect, useState, Suspense, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'motion/react';
import { CheckCircle2, Sparkles, AlertCircle, AlertTriangle, ArrowLeft, Bot } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { useStageStore } from '@/lib/store/stage';
import { useSettingsStore } from '@/lib/store/settings';
import { useAgentRegistry } from '@/lib/orchestration/registry/store';
import { getAvailableProvidersWithVoices } from '@/lib/audio/voice-resolver';
import { useI18n } from '@/lib/hooks/use-i18n';
import {
  loadFileBlob,
  loadImageMapping,
  loadPdfBlob,
  cleanupOldImages,
  storeImages,
} from '@/lib/utils/image-storage';
import { getCurrentModelConfig } from '@/lib/utils/model-config';
import { MAX_PDF_CONTENT_CHARS, MAX_VISION_IMAGES } from '@/lib/constants/generation';
import { nanoid } from 'nanoid';
import type { Stage } from '@/lib/types/stage';
import type { SceneOutline, PdfImage, ImageMapping } from '@/lib/types/generation';
import { AgentRevealModal } from '@/components/agent/agent-reveal-modal';
import { createLogger } from '@/lib/logger';
import { type GenerationSessionState, ALL_STEPS, getActiveSteps } from './types';
import { StepVisualizer } from './components/visualizers';
import { normalizeOutputTypes } from '@/lib/types/output-types';
import {
  buildBackendCoursewareScenes,
  buildBackendStagePatch,
  isBackendCoursewareContent,
} from '@/lib/backend-courseware-scenes';
import { generateTTSForScene } from '@/lib/hooks/use-scene-generator';

const log = createLogger('GenerationPreview');

function uploadReferenceWithProgress(params: {
  file: File;
  sessionId: string;
  index: string;
  purpose: string;
  teacherNote?: string;
  signal?: AbortSignal;
  onProgress?: (loaded: number, total: number) => void;
}): Promise<Record<string, unknown>> {
  const { file, sessionId, index, purpose, teacherNote, signal, onProgress } = params;

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/references/upload');

    const onAbort = () => {
      xhr.abort();
      reject(new DOMException('Aborted', 'AbortError'));
    };

    if (signal) {
      if (signal.aborted) {
        onAbort();
        return;
      }
      signal.addEventListener('abort', onAbort, { once: true });
    }

    xhr.upload.onprogress = (evt) => {
      if (!onProgress) return;
      if (!evt.lengthComputable) {
        onProgress(evt.loaded, file.size || 0);
        return;
      }
      onProgress(evt.loaded, evt.total);
    };

    xhr.onerror = () => {
      reject(new Error('Reference upload failed'));
    };

    xhr.onload = () => {
      const cleanup = () => {
        if (signal) signal.removeEventListener('abort', onAbort);
      };
      cleanup();

      let data: Record<string, unknown> = {};
      try {
        data = (xhr.responseType === 'json' ? xhr.response : null) || JSON.parse(xhr.responseText || '{}');
      } catch {
        data = {};
      }

      if (xhr.status < 200 || xhr.status >= 300) {
        const error =
          typeof data.error === 'string'
            ? data.error
            : `Reference upload failed: ${file.name}`;
        reject(new Error(error));
        return;
      }

      resolve(data);
    };

    const fd = new FormData();
    fd.append('file', file);
    fd.append('session_id', sessionId);
    fd.append('index', index);
    fd.append('purpose', purpose);
    if (teacherNote?.trim()) {
      fd.append('teacher_note', teacherNote.trim());
    }

    xhr.send(fd);
  });
}


function buildTeacherProfileText(requirements: GenerationSessionState['requirements']): string | undefined {
  const lines: string[] = [];
  if (requirements.userNickname?.trim()) {
    lines.push(`Teacher: ${requirements.userNickname.trim()}`);
  }
  if (requirements.userBio?.trim()) {
    lines.push(`Background: ${requirements.userBio.trim()}`);
  }
  const subject = requirements.userSubject?.trim() || '生物';
  lines.push(`Subject: ${subject}`);
  if (requirements.userGradeLevel?.trim()) {
    lines.push(`Target Grade: ${requirements.userGradeLevel.trim()}`);
  }
  if (requirements.userTeachingStyle?.trim()) {
    lines.push(`Teaching Style: ${requirements.userTeachingStyle.trim()}`);
  }

  return lines.length > 0 ? lines.join('\n') : undefined;
}


function buildReferenceUploadLabel(params: {
  language: 'zh-CN' | 'en-US';
  current: number;
  total: number;
  fileName?: string;
}): string {
  const { language, current, total, fileName } = params;
  const base = language === 'zh-CN' ? `上传参考资料 ${current}/${total}` : `Uploading references ${current}/${total}`;
  if (!fileName) return base;
  return `${base}: ${fileName}`;
}

function isAbortLikeError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return true;
  }
  if (error instanceof Error) {
    const normalizedMessage = error.message.trim().toLowerCase();
    return (
      error.name === 'AbortError' ||
      normalizedMessage === 'this operation was aborted' ||
      normalizedMessage === 'aborted'
    );
  }
  return String(error).trim().toLowerCase() === 'this operation was aborted';
}

function toUserFacingGenerationError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  const normalized = raw.toLowerCase();

  if (
    normalized.includes('planning failed') ||
    normalized.includes('modeltimeouterror') ||
    normalized.includes('request timed out')
  ) {
    return '课件规划超时，请稍后重试；若持续出现，可切换更快模型或减少参考资料。';
  }

  if (normalized.includes('backend request timed out') || normalized.includes('backend stream request timed out')) {
    return '后端请求超时，请稍后重试。';
  }

  if (normalized.includes('terminated')) {
    return '生成任务被中断，请重新发起生成。';
  }

  return raw;
}

type CoursewareJobResponse = {
  success?: boolean;
  jobId?: string;
  status?: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  stage?: string;
  progress?: number;
  error?: string | null;
  sessionId?: string;
  versionId?: string | null;
  content?: unknown;
};

function mapJobStageToStepIndex(stage: string, activeSteps: ReturnType<typeof getActiveSteps>): number {
  const stepId =
    stage === 'normalize_input' ||
    stage === 'retrieve_context' ||
    stage === 'generate_outline' ||
    stage === 'queued'
      ? 'outline'
      : stage === 'persist_version' || stage === 'completed'
        ? 'actions'
        : stage.startsWith('generate_')
          ? 'slide-content'
          : 'outline';
  const idx = activeSteps.findIndex((step) => step.id === stepId);
  return idx >= 0 ? idx : 0;
}

function describeJobStage(stage: string): string {
  switch (stage) {
    case 'queued':
      return '任务已创建，等待开始生成。';
    case 'normalize_input':
      return '正在整理教学需求与参考资料。';
    case 'retrieve_context':
      return '正在检索知识库上下文。';
    case 'generate_outline':
      return '正在生成课堂大纲结构。';
    case 'generate_pptx':
      return '正在生成 PPT 课件。';
    case 'generate_docx':
      return '正在生成 Word 教案。';
    case 'generate_game_html':
      return '正在生成互动游戏。';
    case 'generate_animation_html':
      return '正在生成概念动画。';
    case 'persist_version':
      return '正在保存版本与课堂资源。';
    case 'completed':
      return '课件已生成完成，正在进入课堂。';
    case 'cancelled':
      return '任务已取消。';
    default:
      return '正在生成课堂内容。';
  }
}

function GenerationPreviewContent() {
  const router = useRouter();
  const { t } = useI18n();
  const hasStartedRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const runIdRef = useRef(0);
  const disposedRef = useRef(false);

  const [session, setSession] = useState<GenerationSessionState | null>(null);
  const [sessionLoaded, setSessionLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [isComplete] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [uploadProgressPct, setUploadProgressPct] = useState<number | null>(null);
  const [uploadProgressLabel, setUploadProgressLabel] = useState('');
  const [streamingOutlines, setStreamingOutlines] = useState<SceneOutline[] | null>(null);
  const [truncationWarnings, setTruncationWarnings] = useState<string[]>([]);
  const [webSearchSources, setWebSearchSources] = useState<Array<{ title: string; url: string }>>(
    [],
  );
  const [showAgentReveal, setShowAgentReveal] = useState(false);
  const [generatedAgents, setGeneratedAgents] = useState<
    Array<{
      id: string;
      name: string;
      role: string;
      persona: string;
      avatar: string;
      color: string;
      priority: number;
    }>
  >([]);
  const agentRevealResolveRef = useRef<(() => void) | null>(null);

  // Compute active steps based on session state
  const activeSteps = getActiveSteps(session);

  // Load session from sessionStorage
  useEffect(() => {
    cleanupOldImages(24).catch((e) => log.error(e));
    disposedRef.current = false;

    const saved = sessionStorage.getItem('generationSession');
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as GenerationSessionState;
        setSession(parsed);
      } catch (e) {
        log.error('Failed to parse generation session:', e);
      }
    }
    setSessionLoaded(true);
  }, []);

  // Abort all in-flight requests on unmount
  useEffect(() => {
    return () => {
      disposedRef.current = true;
      abortControllerRef.current?.abort();
    };
  }, []);

  // Get API credentials from localStorage
  const getApiHeaders = () => {
    const modelConfig = getCurrentModelConfig();
    const settings = useSettingsStore.getState();
    const imageProviderConfig = settings.imageProvidersConfig?.[settings.imageProviderId];
    const videoProviderConfig = settings.videoProvidersConfig?.[settings.videoProviderId];
    return {
      'Content-Type': 'application/json',
      'x-model': modelConfig.modelString,
      'x-api-key': modelConfig.apiKey,
      'x-base-url': modelConfig.baseUrl,
      'x-provider-type': modelConfig.providerType || '',
      'x-requires-api-key': modelConfig.requiresApiKey ? 'true' : 'false',
      // Image generation provider
      'x-image-provider': settings.imageProviderId || '',
      'x-image-model': settings.imageModelId || '',
      'x-image-api-key': imageProviderConfig?.apiKey || '',
      'x-image-base-url': imageProviderConfig?.baseUrl || '',
      // Video generation provider
      'x-video-provider': settings.videoProviderId || '',
      'x-video-model': settings.videoModelId || '',
      'x-video-api-key': videoProviderConfig?.apiKey || '',
      'x-video-base-url': videoProviderConfig?.baseUrl || '',
      // Media generation toggles
      'x-image-generation-enabled': String(settings.imageGenerationEnabled ?? false),
      'x-video-generation-enabled': String(settings.videoGenerationEnabled ?? false),
    };
  };

  const persistSession = (nextSession: GenerationSessionState) => {
    setSession(nextSession);
    sessionStorage.setItem('generationSession', JSON.stringify(nextSession));
  };

  // Auto-start generation when session is loaded
  useEffect(() => {
    if (session && !hasStartedRef.current) {
      hasStartedRef.current = true;
      startGeneration();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  // Main generation flow
  const startGeneration = async () => {
    if (!session) return;
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;

    // Create AbortController for this generation run
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const signal = controller.signal;

    // Use a local mutable copy so we can update it after PDF parsing
    let currentSession = session;
    let backendReferenceIndexes = Array.from(
      new Set(
        [currentSession.backendReferenceIndex, ...(currentSession.backendReferenceIndexes || [])].filter(
          (v): v is string => !!v,
        ),
      ),
    );
    const outputTypes = normalizeOutputTypes(currentSession.outputTypes);

    setError(null);
    setCurrentStepIndex(0);
    setUploadProgressPct(null);
    setUploadProgressLabel('');

    try {
      const rawSubject = currentSession.requirements.userSubject?.trim() || '';
      const normalizedSubject = rawSubject && rawSubject.includes('生物') ? rawSubject : '生物';
      if (
        !currentSession.outputTypes ||
        currentSession.outputTypes.length !== outputTypes.length ||
        currentSession.outputTypes.some((type, idx) => type !== outputTypes[idx]) ||
        (currentSession.backendReferenceIndexes || []).length !== backendReferenceIndexes.length ||
        currentSession.requirements.userSubject !== normalizedSubject
      ) {
        const hydratedSession = {
          ...currentSession,
          requirements: {
            ...currentSession.requirements,
            userSubject: normalizedSubject,
          },
          outputTypes,
          backendReferenceIndexes,
          backendReferenceIndex: currentSession.backendReferenceIndex || backendReferenceIndexes[0],
        };
        setSession(hydratedSession);
        sessionStorage.setItem('generationSession', JSON.stringify(hydratedSession));
        currentSession = hydratedSession;
      }
      // Compute active steps for this session (recomputed after session mutations)
      let activeSteps = getActiveSteps(currentSession);

      // Determine if we need the PDF analysis step
      const hasPdfToAnalyze = !!currentSession.pdfStorageKey && !currentSession.pdfText;
      // If no PDF to analyze, skip to the next available step
      if (!hasPdfToAnalyze) {
        const firstNonPdfIdx = activeSteps.findIndex((s) => s.id !== 'pdf-analysis');
        setCurrentStepIndex(Math.max(0, firstNonPdfIdx));
      }

      // Step 0: Parse PDF if needed
      if (hasPdfToAnalyze) {
        log.debug('=== Generation Preview: Parsing PDF ===');
        const pdfBlob = await loadPdfBlob(currentSession.pdfStorageKey!);
        if (!pdfBlob) {
          throw new Error(t('generation.pdfLoadFailed'));
        }

        // Ensure pdfBlob is a valid Blob with content
        if (!(pdfBlob instanceof Blob) || pdfBlob.size === 0) {
          log.error('Invalid PDF blob:', {
            type: typeof pdfBlob,
            size: pdfBlob instanceof Blob ? pdfBlob.size : 'N/A',
          });
          throw new Error(t('generation.pdfLoadFailed'));
        }

        // Wrap as a File to guarantee multipart/form-data with correct content-type
        const pdfFile = new File([pdfBlob], currentSession.pdfFileName || 'document.pdf', {
          type: 'application/pdf',
        });

        const parseFormData = new FormData();
        parseFormData.append('pdf', pdfFile);
        parseFormData.append('sessionId', currentSession.backendSessionId || currentSession.sessionId);

        if (currentSession.pdfProviderId) {
          parseFormData.append('providerId', currentSession.pdfProviderId);
        }
        if (currentSession.pdfProviderConfig?.apiKey?.trim()) {
          parseFormData.append('apiKey', currentSession.pdfProviderConfig.apiKey);
        }
        if (currentSession.pdfProviderConfig?.baseUrl?.trim()) {
          parseFormData.append('baseUrl', currentSession.pdfProviderConfig.baseUrl);
        }

        const parseResponse = await fetch('/api/parse-pdf', {
          method: 'POST',
          body: parseFormData,
          signal,
        });

        if (!parseResponse.ok) {
          const errorData = await parseResponse.json();
          throw new Error(errorData.error || t('generation.pdfParseFailed'));
        }

        const parseResult = await parseResponse.json();
        if (!parseResult.success || !parseResult.data) {
          throw new Error(t('generation.pdfParseFailed'));
        }

        let pdfText = parseResult.data.text as string;

        // Truncate if needed
        if (pdfText.length > MAX_PDF_CONTENT_CHARS) {
          pdfText = pdfText.substring(0, MAX_PDF_CONTENT_CHARS);
        }

        // Create image metadata and store images
        // Prefer metadata.pdfImages (both parsers now return this)
        const rawPdfImages = parseResult.data.metadata?.pdfImages;
        const images = rawPdfImages
          ? rawPdfImages.map(
              (img: {
                id: string;
                src?: string;
                pageNumber?: number;
                description?: string;
                width?: number;
                height?: number;
              }) => ({
                id: img.id,
                src: img.src || '',
                pageNumber: img.pageNumber || 1,
                description: img.description,
                width: img.width,
                height: img.height,
              }),
            )
          : (parseResult.data.images as string[]).map((src: string, i: number) => ({
              id: `img_${i + 1}`,
              src,
              pageNumber: 1,
            }));

        const imageStorageIds = await storeImages(images);

        const pdfImages: PdfImage[] = images.map(
          (
            img: {
              id: string;
              src: string;
              pageNumber: number;
              description?: string;
              width?: number;
              height?: number;
            },
            i: number,
          ) => ({
            id: img.id,
            src: '',
            pageNumber: img.pageNumber,
            description: img.description,
            width: img.width,
            height: img.height,
            storageId: imageStorageIds[i],
          }),
        );

        const backendSessionId =
          parseResult.backend?.sessionId || currentSession.backendSessionId || currentSession.sessionId;
        const backendReferenceIndex = parseResult.backend?.index || currentSession.backendReferenceIndex;
        backendReferenceIndexes = Array.from(
          new Set(
            [parseResult.backend?.index, ...backendReferenceIndexes].filter(
              (v): v is string => !!v,
            ),
          ),
        );

        // Update session with parsed PDF data
        const updatedSession = {
          ...currentSession,
          pdfText,
          pdfImages,
          imageStorageIds,
          pdfStorageKey: undefined, // Clear so we don't re-parse
          backendSessionId,
          backendReferenceIndex,
          backendReferenceIndexes,
        };
        setSession(updatedSession);
        sessionStorage.setItem('generationSession', JSON.stringify(updatedSession));

        // Truncation warnings
        const warnings: string[] = [];
        if ((parseResult.data.text as string).length > MAX_PDF_CONTENT_CHARS) {
          warnings.push(
            t('generation.textTruncated').replace('{n}', String(MAX_PDF_CONTENT_CHARS)),
          );
        }
        if (images.length > MAX_VISION_IMAGES) {
          warnings.push(
            t('generation.imageTruncated')
              .replace('{total}', String(images.length))
              .replace('{max}', String(MAX_VISION_IMAGES)),
          );
        }
        if (warnings.length > 0) {
          setTruncationWarnings(warnings);
        }

        // Reassign local reference for subsequent steps
        currentSession = updatedSession;
        activeSteps = getActiveSteps(currentSession);
      }

      // Step: Upload additional reference files (Word/PPT/Image/Video/etc.)
      if (currentSession.referenceFiles && currentSession.referenceFiles.length > 0) {
        const backendSessionId = currentSession.backendSessionId || currentSession.sessionId;
        let backendReferenceIndex = currentSession.backendReferenceIndex || `ref:${backendSessionId}`;

        const uploads: Array<{
          ref: NonNullable<GenerationSessionState['referenceFiles']>[number];
          file: File;
        }> = [];

        for (const ref of currentSession.referenceFiles) {
          const blob = await loadFileBlob(ref.storageKey);
          if (!blob) continue;
          uploads.push({
            ref,
            file: new File([blob], ref.fileName, {
              type: ref.mimeType || blob.type || 'application/octet-stream',
            }),
          });
        }

        const totalBytes = uploads.reduce((sum, item) => sum + Math.max(1, item.file.size), 0);
        let uploadedBytes = 0;

        if (uploads.length > 0) {
          setUploadProgressPct(0);
          setUploadProgressLabel(buildReferenceUploadLabel({ language: currentSession.requirements.language, current: 0, total: uploads.length }));
        }

        for (let i = 0; i < uploads.length; i += 1) {
          const item = uploads[i];
          setUploadProgressLabel(buildReferenceUploadLabel({ language: currentSession.requirements.language, current: i + 1, total: uploads.length, fileName: item.file.name }));

          const uploadData = await uploadReferenceWithProgress({
            file: item.file,
            sessionId: backendSessionId,
            index: backendReferenceIndex,
            purpose: 'reference_upload',
            teacherNote: item.ref.teacherNote,
            signal,
            onProgress: (loaded, total) => {
              const fileTotal = Math.max(1, total || item.file.size || 1);
              const safeLoaded = Math.min(fileTotal, Math.max(0, loaded));
              const pct = Math.round(((uploadedBytes + safeLoaded) / Math.max(1, totalBytes)) * 100);
              setUploadProgressPct(Math.min(100, Math.max(0, pct)));
            },
          });

          const uploadStatus =
            typeof uploadData.status === 'string' ? uploadData.status.toLowerCase() : '';
          const uploadSuccess =
            uploadStatus === 'ok' ||
            uploadData.success === true ||
            (typeof uploadData.index === 'string' && uploadData.index.length > 0);
          if (!uploadSuccess) {
            throw new Error(
              (typeof uploadData.error === 'string' && uploadData.error) ||
                `Reference upload failed: ${item.file.name}`,
            );
          }

          if (typeof uploadData.index === 'string' && uploadData.index) {
            backendReferenceIndex = uploadData.index;
          }
          backendReferenceIndexes = Array.from(
            new Set([...backendReferenceIndexes, backendReferenceIndex]),
          );

          uploadedBytes += Math.max(1, item.file.size);
          setUploadProgressPct(Math.min(100, Math.round((uploadedBytes / Math.max(1, totalBytes)) * 100)));
          setUploadProgressLabel(buildReferenceUploadLabel({ language: currentSession.requirements.language, current: i + 1, total: uploads.length }));
        }

        const updatedSessionWithRefs = {
          ...currentSession,
          backendSessionId,
          backendReferenceIndex,
          backendReferenceIndexes,
        };
        setSession(updatedSessionWithRefs);
        sessionStorage.setItem('generationSession', JSON.stringify(updatedSessionWithRefs));
        currentSession = updatedSessionWithRefs;
        setUploadProgressPct(null);
        setUploadProgressLabel('');
        activeSteps = getActiveSteps(currentSession);
      }
      // Step: Web Search (if enabled)
      const webSearchStepIdx = activeSteps.findIndex((s) => s.id === 'web-search');
      if (currentSession.requirements.webSearch && webSearchStepIdx >= 0) {
        setCurrentStepIndex(webSearchStepIdx);
        setWebSearchSources([]);

        const wsSettings = useSettingsStore.getState();
        const wsApiKey =
          wsSettings.webSearchProvidersConfig?.[wsSettings.webSearchProviderId]?.apiKey;
        const res = await fetch('/api/web-search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: currentSession.requirements.requirement,
            apiKey: wsApiKey || undefined,
          }),
          signal,
        });

        if (!res.ok) {
          const data = await res.json().catch(() => ({ error: 'Web search failed' }));
          throw new Error(data.error || t('generation.webSearchFailed'));
        }

        const searchData = await res.json();
        const sources = (searchData.sources || []).map((s: { title: string; url: string }) => ({
          title: s.title,
          url: s.url,
        }));
        setWebSearchSources(sources);

        const updatedSessionWithSearch = {
          ...currentSession,
          researchContext: searchData.context || '',
          researchSources: sources,
        };
        setSession(updatedSessionWithSearch);
        sessionStorage.setItem('generationSession', JSON.stringify(updatedSessionWithSearch));
        currentSession = updatedSessionWithSearch;
        activeSteps = getActiveSteps(currentSession);
      }

      // Load imageMapping early (needed for both outline and scene generation)
      let imageMapping: ImageMapping = {};
      if (currentSession.imageStorageIds && currentSession.imageStorageIds.length > 0) {
        log.debug('Loading images from IndexedDB');
        imageMapping = await loadImageMapping(currentSession.imageStorageIds);
      } else if (
        currentSession.imageMapping &&
        Object.keys(currentSession.imageMapping).length > 0
      ) {
        log.debug('Using imageMapping from session (old format)');
        imageMapping = currentSession.imageMapping;
      }

      // 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氶梺璇叉唉椤煤閿曞倸鍨傞悹楦挎閺嗭妇绱掔€ｎ収鍤﹂柡鍐ㄧ墕閻掑灚銇勯幒鎴濐仼缁炬儳銈搁弻鏇熺節韫囨搩娲紓浣叉閸嬫挸鈹戦悩鍨毄濠殿喗鎸冲畷鎰磼濡粯鐝烽梺鍝勬川婵嘲螞椤栫偞鐓欐い鏍ф閻ジ宕ョ€ｎ喗鈷戦柛婵嗗閻忛亶鏌涢悩宕囧ⅹ闁伙絽鍢查…銊╁幢閳哄倐顒勬⒑濮瑰洤鐒洪柛銊╀憾閹嫰顢涢悙鑼舵憰闂佹寧绻傞ˇ顖滅不婵犳碍鐓曢柟閭﹀墮缁狙勭箾閸繍鐓兼慨濠冩そ瀹曨偊宕熼浣瑰缂傚倷绀侀鍡涙偋濠婂懎鍨濋悹鍥ㄧゴ濡插牓鏌曡箛鏇炐ユい鏃€鎹囧娲川婵犲倸顫呴梺杞拌閺呯娀寮崒鐐村仼鐎光偓閳ь剟顢?Agent generation (before outlines so persona can influence structure) 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氶梺璇叉唉椤煤閿曞倸鍨傞悹楦挎閺嗭妇绱掔€ｎ収鍤﹂柡鍐ㄧ墕閻掑灚銇勯幒鎴濐仼缁炬儳銈搁弻鏇熺節韫囨搩娲紓浣叉閸嬫挸鈹戦悩鍨毄濠殿喗鎸冲畷鎰磼濡粯鐝烽梺鍝勬川婵嘲螞椤栫偞鐓欐い鏍ф閻ジ宕ョ€ｎ喗鈷戦柛婵嗗閻忛亶鏌涢悩宕囧ⅹ闁伙絽鍢查…銊╁幢閳哄倐顒勬⒑濮瑰洤鐒洪柛銊╀憾閹嫰顢涢悙鑼舵憰闂佹寧绻傞ˇ顖滅不婵犳碍鐓曢柟閭﹀墮缁狙勭箾閸繍鐓兼慨濠冩そ瀹曨偊宕熼浣瑰缂傚倷绀侀鍡涙偋濠婂懎鍨濋悹鍥ㄧゴ濡插牓鏌曡箛鏇炐ユい鏃€鎹囧娲川婵犲倸顫呴梺杞拌閺呯娀寮崒鐐村仼鐎光偓閳ь剟顢?
      const settings = useSettingsStore.getState();
      let agents: Array<{
        id: string;
        name: string;
        role: string;
        persona?: string;
      }> = [];

      // Create stage client-side (needed for agent generation stageId)
      const stageId = nanoid(10);
      let stage: Stage = {
        id: stageId,
        name: extractTopicFromRequirement(currentSession.requirements.requirement),
        description: '',
        language: currentSession.requirements.language || 'zh-CN',
        style: 'professional',
        backendSessionId: currentSession.backendSessionId,
        backendReferenceIndex: currentSession.backendReferenceIndex,
        backendReferenceIndexes: currentSession.backendReferenceIndexes,
        outputTypes,
        createdAt: Date.now(),
        updatedAt: Date.now(),
      };
      const store = useStageStore.getState();

      if (settings.agentMode === 'auto') {
        const agentStepIdx = activeSteps.findIndex((s) => s.id === 'agent-generation');
        if (agentStepIdx >= 0) setCurrentStepIndex(agentStepIdx);

        try {
          const allAvatars = [
            {
              path: '/avatars/teacher.png',
              desc: 'Male teacher with glasses, holding a book, green background',
            },
            {
              path: '/avatars/teacher-2.png',
              desc: 'Female teacher with long dark hair, blue traditional outfit, gentle expression',
            },
            {
              path: '/avatars/assist.png',
              desc: 'Young female assistant with glasses, pink background, friendly smile',
            },
            {
              path: '/avatars/assist-2.png',
              desc: 'Young female in orange top and purple overalls, cheerful and approachable',
            },
            {
              path: '/avatars/clown.png',
              desc: 'Energetic girl with glasses pointing up, green shirt, lively and fun',
            },
            {
              path: '/avatars/clown-2.png',
              desc: 'Playful girl with curly hair doing rock gesture, blue shirt, humorous vibe',
            },
            {
              path: '/avatars/curious.png',
              desc: 'Surprised boy with glasses, hand on cheek, curious expression',
            },
            {
              path: '/avatars/curious-2.png',
              desc: 'Boy with backpack holding a book and question mark bubble, inquisitive',
            },
            {
              path: '/avatars/note-taker.png',
              desc: 'Studious boy with glasses, blue shirt, calm and organized',
            },
            {
              path: '/avatars/note-taker-2.png',
              desc: 'Active boy with yellow backpack waving, blue outfit, enthusiastic learner',
            },
            {
              path: '/avatars/thinker.png',
              desc: 'Thoughtful girl with hand on chin, purple background, contemplative',
            },
            {
              path: '/avatars/thinker-2.png',
              desc: 'Girl reading a book intently, long dark hair, intellectual and focused',
            },
          ];

          const getAvailableVoicesForGeneration = () => {
            const providers = getAvailableProvidersWithVoices(settings.ttsProvidersConfig);
            return providers.flatMap((p) =>
              p.voices.map((v) => ({
                providerId: p.providerId,
                voiceId: v.id,
                voiceName: v.name,
              })),
            );
          };

          // No outlines yet 闂?agent generation uses only stage name + description
          const agentResp = await fetch('/api/generate/agent-profiles', {
            method: 'POST',
            headers: getApiHeaders(),
            body: JSON.stringify({
              stageInfo: { name: stage.name, description: stage.description },
              language: currentSession.requirements.language || 'zh-CN',
              availableAvatars: allAvatars.map((a) => a.path),
              avatarDescriptions: allAvatars.map((a) => ({ path: a.path, desc: a.desc })),
              availableVoices: getAvailableVoicesForGeneration(),
            }),
            signal,
          });

          if (!agentResp.ok) throw new Error('Agent generation failed');
          const agentData = await agentResp.json();
          if (!agentData.success) throw new Error(agentData.error || 'Agent generation failed');

          // Save to IndexedDB and registry
          const { saveGeneratedAgents } = await import('@/lib/orchestration/registry/store');
          const savedIds = await saveGeneratedAgents(stage.id, agentData.agents);
          settings.setSelectedAgentIds(savedIds);

          // Show card-reveal modal, continue generation once all cards are revealed
          setGeneratedAgents(agentData.agents);
          setShowAgentReveal(true);
          await new Promise<void>((resolve) => {
            agentRevealResolveRef.current = resolve;
          });

          agents = savedIds
            .map((id) => useAgentRegistry.getState().getAgent(id))
            .filter(Boolean)
            .map((a) => ({
              id: a!.id,
              name: a!.name,
              role: a!.role,
              persona: a!.persona,
            }));
        } catch (err: unknown) {
          log.warn('[Generation] Agent generation failed, falling back to presets:', err);
          const registry = useAgentRegistry.getState();
          agents = settings.selectedAgentIds
            .map((id) => registry.getAgent(id))
            .filter(Boolean)
            .map((a) => ({
              id: a!.id,
              name: a!.name,
              role: a!.role,
              persona: a!.persona,
            }));
        }
      } else {
        // Preset mode 闂?use selected agents (include persona)
        const registry = useAgentRegistry.getState();
        agents = settings.selectedAgentIds
          .map((id) => registry.getAgent(id))
          .filter(Boolean)
          .map((a) => ({
            id: a!.id,
            name: a!.name,
            role: a!.role,
            persona: a!.persona,
          }));
      }

      const applyBackendJobCompletion = async (content: unknown) => {
        if (!isBackendCoursewareContent(content)) {
          throw new Error('Backend job completed without valid courseware content');
        }

        const backendStagePatch = buildBackendStagePatch(content);
        stage = {
          ...stage,
          ...backendStagePatch,
          backendReferenceIndex: currentSession.backendReferenceIndex,
          backendReferenceIndexes: currentSession.backendReferenceIndexes,
          outputTypes,
          updatedAt: Date.now(),
        };
        store.setStage(stage);

        const backendScenes = buildBackendCoursewareScenes(content, stage.id);
        if (backendScenes.length === 0) {
          throw new Error('Backend courseware did not include any displayable scenes');
        }

        if (settings.ttsEnabled && settings.ttsProviderId !== 'browser-native-tts') {
          const ttsResult = await generateTTSForScene(backendScenes[0], signal);
          if (!ttsResult.success) {
            throw new Error(ttsResult.error || t('generation.speechFailed'));
          }
        }

        store.setScenes(backendScenes);
        store.setCurrentSceneId(backendScenes[0].id);
        store.setGeneratingOutlines([]);

        sessionStorage.removeItem('generationParams');
        sessionStorage.removeItem('generationSession');
        await store.saveToStorage();
        router.push(`/classroom/${stage.id}`);
      };

      const runBackendJobFlow = async (existingJobId?: string) => {
        let jobId = existingJobId;

        if (!jobId) {
          const createResp = await fetch('/api/jobs/courseware', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              requirements: currentSession.requirements,
              backendSessionId: currentSession.backendSessionId || currentSession.sessionId,
              backendReferenceIndex: currentSession.backendReferenceIndex,
              backendReferenceIndexes: currentSession.backendReferenceIndexes,
              outputTypes,
            }),
            signal,
          });

          if (createResp.status === 501 || createResp.status === 404) {
            return false;
          }

          const createData = (await createResp.json().catch(() => ({}))) as CoursewareJobResponse & {
            error?: string;
          };
          if (!createResp.ok || !createData.jobId) {
            throw new Error(createData.error || '创建生成任务失败');
          }

          jobId = createData.jobId;
          currentSession = {
            ...currentSession,
            backendSessionId: createData.sessionId || currentSession.backendSessionId || currentSession.sessionId,
            jobId,
            jobStatus: createData.status || 'queued',
            jobStage: createData.stage || 'queued',
            jobProgress: createData.progress || 0,
            jobError: null,
          };
          persistSession(currentSession);
        }

        while (true) {
          if (signal.aborted || disposedRef.current || runIdRef.current !== runId) {
            return true;
          }

          const statusResp = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
            method: 'GET',
            signal,
            cache: 'no-store',
          });
          const statusData = (await statusResp.json().catch(() => ({}))) as CoursewareJobResponse & {
            error?: string;
          };
          if (!statusResp.ok) {
            throw new Error(statusData.error || '读取生成任务状态失败');
          }

          const nextStatus = statusData.status || 'running';
          const nextStage = statusData.stage || 'queued';
          const nextProgress = statusData.progress ?? currentSession.jobProgress ?? 0;

          currentSession = {
            ...currentSession,
            backendSessionId: statusData.sessionId || currentSession.backendSessionId,
            jobId,
            jobStatus: nextStatus,
            jobStage: nextStage,
            jobProgress: nextProgress,
            jobError: statusData.error || null,
          };
          persistSession(currentSession);

          if (!disposedRef.current && runIdRef.current === runId) {
            setCurrentStepIndex(mapJobStageToStepIndex(nextStage, activeSteps));
            setStatusMessage(`${describeJobStage(nextStage)}${nextProgress ? ` (${nextProgress}%)` : ''}`);
          }

          if (nextStatus === 'succeeded') {
            await applyBackendJobCompletion(statusData.content);
            return true;
          }

          if (nextStatus === 'failed') {
            throw new Error(statusData.error || '课件生成失败');
          }

          if (nextStatus === 'cancelled') {
            throw new Error('任务已取消');
          }

          await new Promise((resolve) => setTimeout(resolve, 3000));
        }
      };

      if (currentSession.jobId) {
        const resumed = await runBackendJobFlow(currentSession.jobId);
        if (resumed) {
          return;
        }
      } else {
        const startedBackendJob = await runBackendJobFlow();
        if (startedBackendJob) {
          return;
        }
      }

      // 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氶梺璇叉唉椤煤閿曞倸鍨傞悹楦挎閺嗭妇绱掔€ｎ収鍤﹂柡鍐ㄧ墕閻掑灚銇勯幒鎴濐仼缁炬儳銈搁弻鏇熺節韫囨搩娲紓浣叉閸嬫挸鈹戦悩鍨毄濠殿喗鎸冲畷鎰磼濡粯鐝烽梺鍝勬川婵嘲螞椤栫偞鐓欐い鏍ф閻ジ宕ョ€ｎ喗鈷戦柛婵嗗閻忛亶鏌涢悩宕囧ⅹ闁伙絽鍢查…銊╁幢閳哄倐顒勬⒑濮瑰洤鐒洪柛銊╀憾閹嫰顢涢悙鑼舵憰闂佹寧绻傞ˇ顖滅不婵犳碍鐓曢柟閭﹀墮缁狙勭箾閸繍鐓兼慨濠冩そ瀹曨偊宕熼浣瑰缂傚倷绀侀鍡涙偋濠婂懎鍨濋悹鍥ㄧゴ濡插牓鏌曡箛鏇炐ユい鏃€鎹囧娲川婵犲倸顫呴梺杞拌閺呯娀寮崒鐐村仼鐎光偓閳ь剟顢?Generate outlines (with agent personas for teacher context) 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氶梺璇叉唉椤煤閿曞倸鍨傞悹楦挎閺嗭妇绱掔€ｎ収鍤﹂柡鍐ㄧ墕閻掑灚銇勯幒鎴濐仼缁炬儳銈搁弻鏇熺節韫囨搩娲紓浣叉閸嬫挸鈹戦悩鍨毄濠殿喗鎸冲畷鎰磼濡粯鐝烽梺鍝勬川婵嘲螞椤栫偞鐓欐い鏍ф閻ジ宕ョ€ｎ喗鈷戦柛婵嗗閻忛亶鏌涢悩宕囧ⅹ闁伙絽鍢查…銊╁幢閳哄倐顒勬⒑濮瑰洤鐒洪柛銊╀憾閹嫰顢涢悙鑼舵憰闂佹寧绻傞ˇ顖滅不婵犳碍鐓曢柟閭﹀墮缁狙勭箾閸繍鐓兼慨濠冩そ瀹曨偊宕熼浣瑰缂傚倷绀侀鍡涙偋濠婂懎鍨濋悹鍥ㄧゴ濡插牓鏌曡箛鏇炐ユい鏃€鎹囧娲川婵犲倸顫呴梺杞拌閺呯娀寮崒鐐村仼鐎光偓閳ь剟顢?
      let outlines = currentSession.sceneOutlines;

      const outlineStepIdx = activeSteps.findIndex((s) => s.id === 'outline');
      setCurrentStepIndex(outlineStepIdx >= 0 ? outlineStepIdx : 0);
      if (!outlines || outlines.length === 0) {
        log.debug('=== Generating outlines (SSE) ===');
        setStreamingOutlines([]);

        outlines = await new Promise<SceneOutline[]>((resolve, reject) => {
          const collected: SceneOutline[] = [];

          fetch('/api/generate/scene-outlines-stream', {
            method: 'POST',
            headers: getApiHeaders(),
            body: JSON.stringify({
              requirements: currentSession.requirements,
              pdfText: currentSession.pdfText,
              pdfImages: currentSession.pdfImages,
              imageMapping,
              researchContext: currentSession.researchContext,
              backendSessionId: currentSession.backendSessionId || currentSession.sessionId,
              backendReferenceIndex: currentSession.backendReferenceIndex,
              backendReferenceIndexes: currentSession.backendReferenceIndexes,
              agents,
            }),
            signal,
          })
            .then((res) => {
              if (!res.ok) {
                return res.json().then((d) => {
                  reject(new Error(d.error || t('generation.outlineGenerateFailed')));
                });
              }

              const reader = res.body?.getReader();
              if (!reader) {
                reject(new Error(t('generation.streamNotReadable')));
                return;
              }

              const decoder = new TextDecoder();
              let sseBuffer = '';

              const pump = (): Promise<void> =>
                reader.read().then(({ done, value }) => {
                  if (value) {
                    sseBuffer += decoder.decode(value, { stream: !done });
                    const lines = sseBuffer.split('\n');
                    sseBuffer = lines.pop() || '';

                    for (const line of lines) {
                      if (!line.startsWith('data: ')) continue;
                      try {
                        const evt = JSON.parse(line.slice(6));
                        if (evt.type === 'outline') {
                          collected.push(evt.data);
                          setStreamingOutlines([...collected]);
                        } else if (evt.type === 'retry') {
                          collected.length = 0;
                          setStreamingOutlines([]);
                          setStatusMessage(t('generation.outlineRetrying'));
                        } else if (evt.type === 'done') {
                          resolve(evt.outlines || collected);
                          return;
                        } else if (evt.type === 'error') {
                          reject(new Error(evt.error));
                          return;
                        }
                      } catch (e) {
                        log.error('Failed to parse outline SSE:', line, e);
                      }
                    }
                  }
                  if (done) {
                    if (collected.length > 0) {
                      resolve(collected);
                    } else {
                      reject(new Error(t('generation.outlineEmptyResponse')));
                    }
                    return;
                  }
                  return pump();
                });

              pump().catch(reject);
            })
            .catch(reject);
        });

        const updatedSession = { ...currentSession, sceneOutlines: outlines };
        setSession(updatedSession);
        sessionStorage.setItem('generationSession', JSON.stringify(updatedSession));

        // Outline generation succeeded 闂?clear homepage draft cache
        try {
          localStorage.removeItem('requirementDraft');
        } catch {
          /* ignore */
        }

        // Brief pause to let user see the final outline state
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }

      // Move to scene generation step
      setStatusMessage('');
      if (!outlines || outlines.length === 0) {
        throw new Error(t('generation.outlineEmptyResponse'));
      }

      // Store stage and outlines
      store.setStage(stage);
      store.setOutlines(outlines);

      // Advance to slide-content step
      const contentStepIdx = activeSteps.findIndex((s) => s.id === 'slide-content');
      if (contentStepIdx >= 0) setCurrentStepIndex(contentStepIdx);

      // Build stageInfo and userProfile for API call
      const stageInfo = {
        name: stage.name,
        description: stage.description,
        language: stage.language,
        style: stage.style,
      };

      const userProfile = buildTeacherProfileText(currentSession.requirements);


      // Generate ONLY the first scene
      store.setGeneratingOutlines(outlines);

      const firstOutline = outlines[0];

      // Step 2: Generate content (currentStepIndex is already 2)
      const contentResp = await fetch('/api/generate/scene-content', {
        method: 'POST',
        headers: getApiHeaders(),
        body: JSON.stringify({
          outline: firstOutline,
          allOutlines: outlines,
          pdfImages: currentSession.pdfImages,
          imageMapping,
          stageInfo,
          stageId: stage.id,
          requirements: currentSession.requirements,
          backendSessionId: currentSession.backendSessionId || currentSession.sessionId,
          backendReferenceIndex: currentSession.backendReferenceIndex,
          backendReferenceIndexes: currentSession.backendReferenceIndexes,
          outputTypes,
          agents,
        }),
        signal,
      });

      if (!contentResp.ok) {
        const errorData = await contentResp.json().catch(() => ({ error: 'Request failed' }));
        throw new Error(errorData.error || t('generation.sceneGenerateFailed'));
      }

      const contentData = await contentResp.json();
      if (!contentData.success || !contentData.content) {
        throw new Error(contentData.error || t('generation.sceneGenerateFailed'));
      }

      const backendSessionIdFromContent =
        typeof contentData.content.sessionId === 'string'
          ? contentData.content.sessionId.trim()
          : '';
      if (
        backendSessionIdFromContent &&
        backendSessionIdFromContent !== currentSession.backendSessionId
      ) {
        const syncedSession = {
          ...currentSession,
          backendSessionId: backendSessionIdFromContent,
        };
        currentSession = syncedSession;
        sessionStorage.setItem('generationSession', JSON.stringify(syncedSession));
      }
      if (backendSessionIdFromContent && backendSessionIdFromContent !== stage.backendSessionId) {
        stage = {
          ...stage,
          backendSessionId: backendSessionIdFromContent,
          backendReferenceIndex: currentSession.backendReferenceIndex,
          backendReferenceIndexes: currentSession.backendReferenceIndexes,
          outputTypes,
          updatedAt: Date.now(),
        };
        // Safe here because no scene has been added yet.
        store.setStage(stage);
      }

      if (isBackendCoursewareContent(contentData.content)) {
        const backendStagePatch = buildBackendStagePatch(contentData.content);
        stage = {
          ...stage,
          ...backendStagePatch,
          backendReferenceIndex: currentSession.backendReferenceIndex,
          backendReferenceIndexes: currentSession.backendReferenceIndexes,
          outputTypes,
          updatedAt: Date.now(),
        };
        store.setStage(stage);

        const backendScenes = buildBackendCoursewareScenes(contentData.content, stage.id);
        if (backendScenes.length === 0) {
          throw new Error('Backend courseware did not include any displayable scenes');
        }

        if (settings.ttsEnabled && settings.ttsProviderId !== 'browser-native-tts') {
          const ttsResult = await generateTTSForScene(backendScenes[0], signal);
          if (!ttsResult.success) {
            throw new Error(ttsResult.error || t('generation.speechFailed'));
          }
        }

        store.setScenes(backendScenes);
        store.setCurrentSceneId(backendScenes[0].id);
        store.setGeneratingOutlines([]);

        sessionStorage.removeItem('generationParams');
        sessionStorage.removeItem('generationSession');
        await store.saveToStorage();
        router.push(`/classroom/${stage.id}`);
        return;
      }

      // Generate actions (activate actions step indicator)
      const actionsStepIdx = activeSteps.findIndex((s) => s.id === 'actions');
      setCurrentStepIndex(actionsStepIdx >= 0 ? actionsStepIdx : currentStepIndex + 1);

      const actionsResp = await fetch('/api/generate/scene-actions', {
        method: 'POST',
        headers: getApiHeaders(),
        body: JSON.stringify({
          outline: contentData.effectiveOutline || firstOutline,
          allOutlines: outlines,
          content: contentData.content,
          stageId: stage.id,
          requirements: currentSession.requirements,
          agents,
          previousSpeeches: [],
          userProfile,
        }),
        signal,
      });

      if (!actionsResp.ok) {
        const errorData = await actionsResp.json().catch(() => ({ error: 'Request failed' }));
        throw new Error(errorData.error || t('generation.sceneGenerateFailed'));
      }

      const data = await actionsResp.json();
      if (!data.success || !data.scene) {
        throw new Error(data.error || t('generation.sceneGenerateFailed'));
      }

      // Generate TTS for first scene (part of actions step 闂?blocking)
      if (settings.ttsEnabled && settings.ttsProviderId !== 'browser-native-tts') {
        const ttsResult = await generateTTSForScene(data.scene, signal);
        if (!ttsResult.success) {
          throw new Error(ttsResult.error || t('generation.speechFailed'));
        }
      }

      // Add scene to store and navigate
      store.addScene(data.scene);
      store.setCurrentSceneId(data.scene.id);

      // Set remaining outlines as skeleton placeholders
      const remaining = outlines.filter((o) => o.order !== data.scene.order);
      store.setGeneratingOutlines(remaining);

      // Store generation params for classroom to continue generation
      sessionStorage.setItem(
        'generationParams',
        JSON.stringify({
          pdfImages: currentSession.pdfImages,
          agents,
          userProfile,
          outputTypes,
          backendSessionId: currentSession.backendSessionId,
          backendReferenceIndex: currentSession.backendReferenceIndex,
          backendReferenceIndexes: currentSession.backendReferenceIndexes,
        }),
      );

      sessionStorage.removeItem('generationSession');
      await store.saveToStorage();
      router.push(`/classroom/${stage.id}`);
    } catch (err) {
      if (disposedRef.current || runIdRef.current !== runId) {
        return;
      }
      // AbortError is expected when navigating away 闂?don't show as error
      if (isAbortLikeError(err)) {
        log.info('[GenerationPreview] Generation aborted');
        return;
      }
      setError(toUserFacingGenerationError(err));
    }
  };

  const extractTopicFromRequirement = (requirement: string): string => {
    const trimmed = requirement.trim();
    if (trimmed.length <= 500) {
      return trimmed;
    }
    return trimmed.substring(0, 500).trim() + '...';
  };

  const goBackToHome = () => {
    abortControllerRef.current?.abort();
    sessionStorage.removeItem('generationSession');
    router.push('/');
  };

  // Still loading session from sessionStorage
  if (!sessionLoaded) {
    return (
      <div className="min-h-[100dvh] w-full bg-gradient-to-b from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900 flex items-center justify-center p-4">
        <div className="text-center text-muted-foreground">
          <div className="size-8 border-2 border-current border-t-transparent rounded-full animate-spin mx-auto" />
        </div>
      </div>
    );
  }

  // No session found
  if (!session) {
    return (
      <div className="min-h-[100dvh] w-full bg-gradient-to-b from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900 flex items-center justify-center p-4">
        <Card className="p-8 max-w-md w-full">
          <div className="text-center space-y-4">
            <AlertCircle className="size-12 text-muted-foreground mx-auto" />
            <h2 className="text-xl font-semibold">{t('generation.sessionNotFound')}</h2>
            <p className="text-sm text-muted-foreground">{t('generation.sessionNotFoundDesc')}</p>
            <Button onClick={() => router.push('/')} className="w-full">
              <ArrowLeft className="size-4 mr-2" />
              {t('generation.backToHome')}
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  const activeStep =
    activeSteps.length > 0
      ? activeSteps[Math.min(currentStepIndex, activeSteps.length - 1)]
      : ALL_STEPS[0];

  return (
    <div className="min-h-[100dvh] w-full bg-gradient-to-b from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900 flex flex-col items-center justify-center p-4 relative overflow-hidden text-center">
      {/* Background Decor */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        <div
          className="absolute top-0 left-1/4 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl animate-pulse"
          style={{ animationDuration: '4s' }}
        />
        <div
          className="absolute bottom-0 right-1/4 w-96 h-96 bg-purple-500/10 rounded-full blur-3xl animate-pulse"
          style={{ animationDuration: '6s' }}
        />
      </div>

      {/* Back button */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="absolute top-4 left-4 z-20"
      >
        <Button variant="ghost" size="sm" onClick={goBackToHome}>
          <ArrowLeft className="size-4 mr-2" />
          {t('generation.backToHome')}
        </Button>
      </motion.div>

      <div className="z-10 w-full max-w-lg space-y-8 flex flex-col items-center">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="w-full"
        >
          <Card className="relative overflow-hidden border-muted/40 shadow-2xl bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl min-h-[400px] flex flex-col items-center justify-center p-8 md:p-12">
            {/* Progress Dots */}
            <div className="absolute top-6 left-0 right-0 flex justify-center gap-2">
              {activeSteps.map((step, idx) => (
                <div
                  key={step.id}
                  className={cn(
                    'h-1.5 rounded-full transition-all duration-500',
                    idx < currentStepIndex
                      ? 'w-1.5 bg-blue-500/30'
                      : idx === currentStepIndex
                        ? 'w-8 bg-blue-500'
                        : 'w-1.5 bg-muted/50',
                  )}
                />
              ))}
            </div>

            {/* Central Content */}
            <div className="flex-1 flex flex-col items-center justify-center w-full space-y-8 mt-4">
              {/* Icon / Visualizer Container */}
              <div className="relative size-48 flex items-center justify-center">
                <AnimatePresence mode="popLayout">
                  {error ? (
                    <motion.div
                      key="error"
                      initial={{ scale: 0.5, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      className="size-32 rounded-full bg-red-500/10 flex items-center justify-center border-2 border-red-500/20"
                    >
                      <AlertCircle className="size-16 text-red-500" />
                    </motion.div>
                  ) : isComplete ? (
                    <motion.div
                      key="complete"
                      initial={{ scale: 0.5, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      className="size-32 rounded-full bg-green-500/10 flex items-center justify-center border-2 border-green-500/20"
                    >
                      <CheckCircle2 className="size-16 text-green-500" />
                    </motion.div>
                  ) : (
                    <motion.div
                      key={activeStep.id}
                      initial={{ scale: 0.8, opacity: 0, filter: 'blur(10px)' }}
                      animate={{ scale: 1, opacity: 1, filter: 'blur(0px)' }}
                      exit={{ scale: 1.2, opacity: 0, filter: 'blur(10px)' }}
                      transition={{ duration: 0.4 }}
                      className="absolute inset-0 flex items-center justify-center"
                    >
                      <StepVisualizer
                        stepId={activeStep.id}
                        outlines={streamingOutlines}
                        webSearchSources={webSearchSources}
                      />
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Text Content */}
              <div className="space-y-3 max-w-sm mx-auto">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={error ? 'error' : isComplete ? 'done' : activeStep.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className="space-y-2"
                  >
                    <h2 className="text-2xl font-bold tracking-tight">
                      {error
                        ? t('generation.generationFailed')
                        : isComplete
                          ? t('generation.generationComplete')
                          : t(activeStep.title)}
                    </h2>
                    <p className="text-muted-foreground text-base">
                      {error
                        ? error
                        : isComplete
                          ? t('generation.classroomReady')
                          : statusMessage || t(activeStep.description)}
                    </p>
                  </motion.div>
                </AnimatePresence>

                {uploadProgressPct !== null && !error && !isComplete && (
                  <motion.div
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mx-auto w-full max-w-sm rounded-lg border border-blue-200/50 bg-blue-50/50 px-3 py-2 dark:border-blue-900/40 dark:bg-blue-950/20"
                  >
                    <div className="mb-1 flex items-center justify-between gap-3 text-[11px] text-blue-700 dark:text-blue-300">
                      <span className="truncate">
                        {uploadProgressLabel || (session?.requirements.language === 'zh-CN' ? '上传参考资料中' : 'Uploading references')}
                      </span>
                      <span className="font-semibold tabular-nums">{uploadProgressPct}%</span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-blue-200/60 dark:bg-blue-900/40">
                      <div
                        className="h-full rounded-full bg-blue-500 transition-[width] duration-200"
                        style={{ width: `${uploadProgressPct}%` }}
                      />
                    </div>
                  </motion.div>
                )}

                {/* Truncation warning indicator */}
                <AnimatePresence>
                  {truncationWarnings.length > 0 && !error && !isComplete && (
                    <motion.div
                      initial={{ opacity: 0, scale: 0 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0 }}
                      transition={{
                        type: 'spring',
                        stiffness: 500,
                        damping: 30,
                      }}
                      className="flex justify-center"
                    >
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <motion.button
                            type="button"
                            animate={{
                              boxShadow: [
                                '0 0 0 0 rgba(251, 191, 36, 0), 0 0 0 0 rgba(251, 191, 36, 0)',
                                '0 0 16px 4px rgba(251, 191, 36, 0.12), 0 0 4px 1px rgba(251, 191, 36, 0.08)',
                                '0 0 0 0 rgba(251, 191, 36, 0), 0 0 0 0 rgba(251, 191, 36, 0)',
                              ],
                            }}
                            transition={{
                              duration: 3,
                              repeat: Infinity,
                              ease: 'easeInOut',
                            }}
                            className="relative size-7 rounded-full flex items-center justify-center cursor-default
                                       bg-gradient-to-br from-amber-400/15 to-orange-400/10
                                       border border-amber-400/25 hover:border-amber-400/40
                                       hover:from-amber-400/20 hover:to-orange-400/15
                                       transition-colors duration-300
                                       focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/30"
                          >
                            <AlertTriangle
                              className="size-3.5 text-amber-500 dark:text-amber-400"
                              strokeWidth={2.5}
                            />
                          </motion.button>
                        </TooltipTrigger>
                        <TooltipContent side="bottom" sideOffset={6}>
                          <div className="space-y-1 py-0.5">
                            {truncationWarnings.map((w, i) => (
                              <p key={i} className="text-xs leading-relaxed">
                                {w}
                              </p>
                            ))}
                          </div>
                        </TooltipContent>
                      </Tooltip>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </Card>
        </motion.div>

        {/* Footer Action */}
        <div className="h-16 flex items-center justify-center w-full">
          <AnimatePresence>
            {error ? (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="w-full max-w-xs"
              >
                <Button size="lg" variant="outline" className="w-full h-12" onClick={goBackToHome}>
                  {t('generation.goBackAndRetry')}
                </Button>
              </motion.div>
            ) : !isComplete ? (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center gap-3 text-sm text-muted-foreground/50 font-medium uppercase tracking-widest"
              >
                <Sparkles className="size-3 animate-pulse" />
                {t('generation.aiWorking')}
                {generatedAgents.length > 0 && !showAgentReveal && (
                  <button
                    onClick={() => setShowAgentReveal(true)}
                    className="ml-2 flex items-center gap-1.5 rounded-full border border-purple-300/30 bg-purple-500/10 px-3 py-1 text-xs font-medium normal-case tracking-normal text-purple-400 transition-colors hover:bg-purple-500/20 hover:text-purple-300"
                  >
                    <Bot className="size-3" />
                    {t('generation.viewAgents')}
                  </button>
                )}
              </motion.div>
            ) : null}
          </AnimatePresence>
        </div>
      </div>

      {/* Agent Reveal Modal */}
      <AgentRevealModal
        agents={generatedAgents}
        open={showAgentReveal}
        onClose={() => setShowAgentReveal(false)}
        onAllRevealed={() => {
          agentRevealResolveRef.current?.();
          agentRevealResolveRef.current = null;
        }}
      />
    </div>
  );
}

export default function GenerationPreviewPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-[100dvh] w-full bg-gradient-to-b from-slate-50 to-slate-100 dark:from-slate-950 dark:to-slate-900 flex items-center justify-center">
          <div className="animate-pulse space-y-4 text-center">
            <div className="h-8 w-48 bg-muted rounded mx-auto" />
            <div className="h-4 w-64 bg-muted rounded mx-auto" />
          </div>
        </div>
      }
    >
      <GenerationPreviewContent />
    </Suspense>
  );
}















