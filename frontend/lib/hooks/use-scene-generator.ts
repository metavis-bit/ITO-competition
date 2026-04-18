'use client';

import { useCallback, useRef } from 'react';
import { useStageStore } from '@/lib/store/stage';
import { getCurrentModelConfig } from '@/lib/utils/model-config';
import { useSettingsStore } from '@/lib/store/settings';
import { db } from '@/lib/utils/database';
import type { SceneOutline, PdfImage, ImageMapping } from '@/lib/types/generation';
import type { AgentInfo } from '@/lib/generation/generation-pipeline';
import type { Scene } from '@/lib/types/stage';
import type { Action, SpeechAction } from '@/lib/types/action';
import type { TTSProviderId } from '@/lib/audio/types';
import type { OutputArtifactType } from '@/lib/types/output-types';
import { splitLongSpeechActions } from '@/lib/audio/tts-utils';
import { generateMediaForOutlines } from '@/lib/media/media-orchestrator';
import { createLogger } from '@/lib/logger';
import { nanoid } from 'nanoid';
import {
  buildBackendCoursewareScenes,
  buildBackendStagePatch,
  isBackendCoursewareContent,
} from '@/lib/backend-courseware-scenes';
import { matchBiologyImage, getBiologyImageUrl, resetUsedImages } from '@/lib/utils/biology-images';

const log = createLogger('SceneGenerator');

/** Check if content was returned from the backend proxy (artifacts-based) */
function isBackendContent(content: unknown): content is {
  sessionId: string;
  versionId: string | null;
  artifacts: Array<{ artifact_id: string; type: string; file_path: string; metadata: Record<string, unknown> }>;
  plan?: { slide_count: number; game_count: number; intent: string };
} {
  return !!content && typeof content === 'object' && 'artifacts' in content;
}

/** Build a Scene directly from backend artifacts, skipping the scene-actions step */
function buildSceneFromBackendContent(
  outline: SceneOutline,
  content: ReturnType<typeof isBackendContent extends (c: unknown) => c is infer R ? () => R : never>,
  stageId: string,
): Scene {
  const backendContent = content as {
    sessionId: string;
    versionId: string | null;
    artifacts: Array<{ artifact_id: string; type: string; file_path: string; metadata: Record<string, unknown> }>;
    plan?: { slide_count: number; game_count: number; intent: string };
  };

  // Build a placeholder slide scene with a speech action describing the content
  const speechText = outline.description || outline.keyPoints?.join('。') || outline.title;
  const actions: Action[] = [
    {
      id: `action_${nanoid(8)}`,
      type: 'speech',
      title: '场景讲解',
      text: speechText,
    },
  ];

  // Map backend artifact types to scene types
  const sceneType = outline.type === 'interactive' ? 'interactive' : 'slide';

  if (sceneType === 'interactive') {
    const htmlArtifact = backendContent.artifacts.find(
      (a) =>
        a.type === 'game_html' ||
        a.type === 'animation_html' ||
        a.type === 'game' ||
        a.type === 'html',
    );
    return {
      id: nanoid(),
      stageId,
      type: 'interactive',
      title: outline.title,
      order: outline.order,
      content: {
        type: 'interactive',
        url: '',
        html: (htmlArtifact?.metadata?.html as string) || `<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:24px">${outline.title}</div>`,
      },
      actions,
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };
  }

  // Default: build a slide scene with title + matched biology image
  const matchedImage = matchBiologyImage(outline.title, outline.description);
  const hasImage = !!matchedImage;
  const imageUrl = matchedImage ? getBiologyImageUrl(matchedImage) : '';

  // Layout: if image matched, use left-text + right-image layout
  const textElements: Array<{
    id: string; type: 'text'; left: number; top: number; width: number; height: number;
    content: string; rotate: number; defaultFontName: string; defaultColor: string;
  }> = [
    {
      id: nanoid(),
      type: 'text' as const,
      left: hasImage ? 40 : 50,
      top: hasImage ? 80 : 200,
      width: hasImage ? 480 : 900,
      height: 120,
      content: `<p style="text-align:${hasImage ? 'left' : 'center'};font-size:32px;font-weight:bold;color:#1a5c3a">${outline.title}</p>`,
      rotate: 0,
      defaultFontName: 'Microsoft YaHei',
      defaultColor: '#1a5c3a',
    },
  ];

  if (outline.description) {
    textElements.push({
      id: nanoid(),
      type: 'text' as const,
      left: hasImage ? 40 : 100,
      top: hasImage ? 220 : 340,
      width: hasImage ? 480 : 800,
      height: hasImage ? 280 : 120,
      content: `<p style="text-align:left;font-size:16px;color:#444;line-height:1.8">${outline.description}</p>`,
      rotate: 0,
      defaultFontName: 'Microsoft YaHei',
      defaultColor: '#444444',
    });
  }

  if (outline.keyPoints?.length) {
    const bulletHtml = outline.keyPoints.map((p) => `<li>${p}</li>`).join('');
    textElements.push({
      id: nanoid(),
      type: 'text' as const,
      left: hasImage ? 40 : 80,
      top: hasImage ? (outline.description ? 400 : 220) : 420,
      width: hasImage ? 480 : 840,
      height: 140,
      content: `<ul style="font-size:14px;color:#555;line-height:2">${bulletHtml}</ul>`,
      rotate: 0,
      defaultFontName: 'Microsoft YaHei',
      defaultColor: '#555555',
    });
  }

  const imageElements = hasImage ? [{
    id: nanoid(),
    type: 'image' as const,
    left: 550,
    top: 60,
    width: 420,
    height: 440,
    src: imageUrl,
    rotate: 0,
    fixedRatio: true,
  }] : [];

  return {
    id: nanoid(),
    stageId,
    type: 'slide',
    title: outline.title,
    order: outline.order,
    content: {
      type: 'slide',
      canvas: {
        id: nanoid(),
        viewportSize: 1000,
        viewportRatio: 0.5625,
        theme: {
          backgroundColor: '#f0faf4',
          themeColors: ['#1a5c3a', '#2d8f5e', '#5bb583', '#a5d6a7', '#e8f5e9'],
          fontColor: '#1a5c3a',
          fontName: 'Microsoft YaHei',
          outline: { color: '#2d8f5e', width: 1, style: 'solid' },
          shadow: { h: 0, v: 2, blur: 8, color: '#00000015' },
        },
        elements: [...textElements, ...imageElements],
        background: { type: 'solid' as const, color: '#f0faf4' },
      },
    },
    actions,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
}

interface SceneContentResult {
  success: boolean;
  content?: unknown;
  effectiveOutline?: SceneOutline;
  error?: string;
}

interface SceneActionsResult {
  success: boolean;
  scene?: Scene;
  previousSpeeches?: string[];
  error?: string;
}

function getApiHeaders(): HeadersInit {
  const config = getCurrentModelConfig();
  const settings = useSettingsStore.getState();
  const imageProviderConfig = settings.imageProvidersConfig?.[settings.imageProviderId];
  const videoProviderConfig = settings.videoProvidersConfig?.[settings.videoProviderId];

  return {
    'Content-Type': 'application/json',
    'x-model': config.modelString || '',
    'x-api-key': config.apiKey || '',
    'x-base-url': config.baseUrl || '',
    'x-provider-type': config.providerType || '',
    'x-requires-api-key': String(config.requiresApiKey ?? false),
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
}

/** Call POST /api/generate/scene-content (step 1) */
async function fetchSceneContent(
  params: {
    outline: SceneOutline;
    allOutlines: SceneOutline[];
    stageId: string;
    pdfImages?: PdfImage[];
    imageMapping?: ImageMapping;
    stageInfo: {
      name: string;
      description?: string;
      language?: string;
      style?: string;
    };
    agents?: AgentInfo[];
    outputTypes?: OutputArtifactType[];
    backendSessionId?: string;
    backendReferenceIndex?: string;
    backendReferenceIndexes?: string[];
  },
  signal?: AbortSignal,
): Promise<SceneContentResult> {
  const response = await fetch('/api/generate/scene-content', {
    method: 'POST',
    headers: getApiHeaders(),
    body: JSON.stringify(params),
    signal,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({ error: 'Request failed' }));
    return { success: false, error: data.error || `HTTP ${response.status}` };
  }

  return response.json();
}

/** Call POST /api/generate/scene-actions (step 2) */
async function fetchSceneActions(
  params: {
    outline: SceneOutline;
    allOutlines: SceneOutline[];
    content: unknown;
    stageId: string;
    agents?: AgentInfo[];
    previousSpeeches?: string[];
    userProfile?: string;
  },
  signal?: AbortSignal,
): Promise<SceneActionsResult> {
  const response = await fetch('/api/generate/scene-actions', {
    method: 'POST',
    headers: getApiHeaders(),
    body: JSON.stringify(params),
    signal,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({ error: 'Request failed' }));
    return { success: false, error: data.error || `HTTP ${response.status}` };
  }

  return response.json();
}

/** Generate TTS for one speech action and store in IndexedDB */
export async function generateAndStoreTTS(
  audioId: string,
  text: string,
  signal?: AbortSignal,
): Promise<void> {
  const settings = useSettingsStore.getState();
  if (settings.ttsProviderId === 'browser-native-tts') return;

  const ttsProviderConfig = settings.ttsProvidersConfig?.[settings.ttsProviderId];
  const response = await fetch('/api/generate/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      audioId,
      ttsProviderId: settings.ttsProviderId,
      ttsVoice: settings.ttsVoice,
      ttsSpeed: settings.ttsSpeed,
      ttsApiKey: ttsProviderConfig?.apiKey || undefined,
      ttsBaseUrl: ttsProviderConfig?.baseUrl || undefined,
    }),
    signal,
  });

  const data = await response
    .json()
    .catch(() => ({ success: false, error: response.statusText || 'Invalid TTS response' }));
  if (!response.ok || !data.success || !data.base64 || !data.format) {
    const err = new Error(
      data.details || data.error || `TTS request failed: HTTP ${response.status}`,
    );
    log.warn('TTS failed for', audioId, ':', err);
    throw err;
  }

  const binary = atob(data.base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const blob = new Blob([bytes], { type: `audio/${data.format}` });
  await db.audioFiles.put({
    id: audioId,
    blob,
    format: data.format,
    createdAt: Date.now(),
  });
}

/** Generate TTS for all speech actions in a scene. Returns result. */
export async function generateTTSForScene(
  scene: Scene,
  signal?: AbortSignal,
): Promise<{ success: boolean; failedCount: number; error?: string }> {
  const providerId = useSettingsStore.getState().ttsProviderId;
  scene.actions = splitLongSpeechActions(scene.actions || [], providerId);
  const speechActions = scene.actions.filter(
    (a): a is SpeechAction => a.type === 'speech' && !!a.text,
  );
  if (speechActions.length === 0) return { success: true, failedCount: 0 };

  let failedCount = 0;
  let lastError: string | undefined;

  for (const action of speechActions) {
    const audioId = `tts_${action.id}`;
    action.audioId = audioId;
    try {
      await generateAndStoreTTS(audioId, action.text, signal);
    } catch (error) {
      failedCount++;
      lastError = error instanceof Error ? error.message : `TTS failed for action ${action.id}`;
      log.warn('TTS generation failed:', {
        providerId,
        actionId: action.id,
        textLength: action.text.length,
        error: lastError,
      });
    }
  }

  return {
    success: failedCount === 0,
    failedCount,
    error: lastError,
  };
}

export interface UseSceneGeneratorOptions {
  onSceneGenerated?: (scene: Scene, index: number) => void;
  onSceneFailed?: (outline: SceneOutline, error: string) => void;
  onPhaseChange?: (phase: 'content' | 'actions', outline: SceneOutline) => void;
  onComplete?: () => void;
}

export interface GenerationParams {
  pdfImages?: PdfImage[];
  imageMapping?: ImageMapping;
  stageInfo: {
    name: string;
    description?: string;
    language?: string;
    style?: string;
  };
  agents?: AgentInfo[];
  userProfile?: string;
  outputTypes?: OutputArtifactType[];
  backendSessionId?: string;
  backendReferenceIndex?: string;
  backendReferenceIndexes?: string[];
}

export function useSceneGenerator(options: UseSceneGeneratorOptions = {}) {
  const abortRef = useRef(false);
  const generatingRef = useRef(false);
  const mediaAbortRef = useRef<AbortController | null>(null);
  const fetchAbortRef = useRef<AbortController | null>(null);
  const lastParamsRef = useRef<GenerationParams | null>(null);
  const generateRemainingRef = useRef<((params: GenerationParams) => Promise<void>) | null>(null);

  const store = useStageStore;

  const applyBackendContentToStore = useCallback(
    (content: unknown, stageId: string) => {
      if (!isBackendCoursewareContent(content)) return null;

      const backendScenes = buildBackendCoursewareScenes(content, stageId);
      const state = store.getState();
      const currentStage = state.stage;
      if (currentStage) {
        store.setState({
          stage: {
            ...currentStage,
            ...buildBackendStagePatch(content),
            updatedAt: Date.now(),
          },
          scenes: backendScenes,
          currentSceneId: backendScenes[0]?.id || null,
          generatingOutlines: [],
          failedOutlines: [],
        });
        void store.getState().saveToStorage();
      }

      return backendScenes;
    },
    [store],
  );

  const generateRemaining = useCallback(
    async (params: GenerationParams) => {
      lastParamsRef.current = params;
      if (generatingRef.current) return;
      generatingRef.current = true;
      abortRef.current = false;
      resetUsedImages();
      const removeGeneratingOutline = (outlineId: string) => {
        const current = store.getState().generatingOutlines;
        if (!current.some((o) => o.id === outlineId)) return;
        store.getState().setGeneratingOutlines(current.filter((o) => o.id !== outlineId));
      };

      // Create a new AbortController for this generation run
      fetchAbortRef.current = new AbortController();
      const signal = fetchAbortRef.current.signal;

      const state = store.getState();
      const { outlines, scenes, stage } = state;
      const startEpoch = state.generationEpoch;
      if (!stage || outlines.length === 0) {
        generatingRef.current = false;
        return;
      }

      store.getState().setGenerationStatus('generating');

      // Determine pending outlines
      const completedOrders = new Set(scenes.map((s) => s.order));
      const pending = outlines
        .filter((o) => !completedOrders.has(o.order))
        .sort((a, b) => a.order - b.order);

      if (pending.length === 0) {
        store.getState().setGenerationStatus('completed');
        store.getState().setGeneratingOutlines([]);
        options.onComplete?.();
        generatingRef.current = false;
        return;
      }

      store.getState().setGeneratingOutlines(pending);

      // Launch media generation in parallel 鈥?does not block content/action generation
      mediaAbortRef.current = new AbortController();
      generateMediaForOutlines(outlines, stage.id, mediaAbortRef.current.signal).catch((err) => {
        log.warn('Media generation error:', err);
      });

      // Get previousSpeeches from last completed scene
      let previousSpeeches: string[] = [];
      const sortedScenes = [...scenes].sort((a, b) => a.order - b.order);
      if (sortedScenes.length > 0) {
        const lastScene = sortedScenes[sortedScenes.length - 1];
        previousSpeeches = (lastScene.actions || [])
          .filter((a): a is SpeechAction => a.type === 'speech')
          .map((a) => a.text);
      }

      // Serial generation loop 鈥?two-step per outline
      try {
        let pausedByFailureOrAbort = false;
        for (const outline of pending) {
          if (abortRef.current || store.getState().generationEpoch !== startEpoch) {
            store.getState().setGenerationStatus('paused');
            pausedByFailureOrAbort = true;
            break;
          }

          store.getState().setCurrentGeneratingOrder(outline.order);

          // Step 1: Generate content
          options.onPhaseChange?.('content', outline);
          const contentResult = await fetchSceneContent(
            {
              outline,
              allOutlines: outlines,
              stageId: stage.id,
              pdfImages: params.pdfImages,
              imageMapping: params.imageMapping,
              stageInfo: params.stageInfo,
              agents: params.agents,
              outputTypes: params.outputTypes,
              backendSessionId: params.backendSessionId,
              backendReferenceIndex: params.backendReferenceIndex,
              backendReferenceIndexes: params.backendReferenceIndexes,
            },
            signal,
          );

          if (!contentResult.success || !contentResult.content) {
            if (abortRef.current || store.getState().generationEpoch !== startEpoch) {
              pausedByFailureOrAbort = true;
              break;
            }
            store.getState().addFailedOutline(outline);
            options.onSceneFailed?.(outline, contentResult.error || 'Content generation failed');
            store.getState().setGenerationStatus('paused');
            pausedByFailureOrAbort = true;
            break;
          }

          if (abortRef.current || store.getState().generationEpoch !== startEpoch) {
            store.getState().setGenerationStatus('paused');
            pausedByFailureOrAbort = true;
            break;
          }

          // Step 2: Generate actions + assemble scene
          options.onPhaseChange?.('actions', outline);

          let scene: Scene | undefined;
          let outputPreviousSpeeches: string[] = [];

          // Backend mode: one backend response already contains the full courseware.
          if (isBackendCoursewareContent(contentResult.content)) {
            log.info(`Backend courseware detected for "${outline.title}", applying full result`);
            const backendScenes = applyBackendContentToStore(contentResult.content, stage.id);
            if (!backendScenes || backendScenes.length === 0) {
              store.getState().addFailedOutline(outline);
              options.onSceneFailed?.(outline, 'Backend courseware did not include any displayable scenes');
              store.getState().setGenerationStatus('paused');
              pausedByFailureOrAbort = true;
              break;
            }

            backendScenes.forEach((generatedScene) => {
              options.onSceneGenerated?.(generatedScene, generatedScene.order);
            });
            store.getState().setCurrentGeneratingOrder(-1);
            store.getState().setGeneratingOutlines([]);
            store.getState().setGenerationStatus('completed');
            options.onComplete?.();
            return;
          } else {
            // Frontend mode: call scene-actions API
            const actionsResult = await fetchSceneActions(
              {
                outline: contentResult.effectiveOutline || outline,
                allOutlines: outlines,
                content: contentResult.content,
                stageId: stage.id,
                agents: params.agents,
                previousSpeeches,
                userProfile: params.userProfile,
              },
              signal,
            );

            if (actionsResult.success && actionsResult.scene) {
              scene = actionsResult.scene;
              outputPreviousSpeeches = actionsResult.previousSpeeches || [];
            } else {
              if (abortRef.current || store.getState().generationEpoch !== startEpoch) {
                pausedByFailureOrAbort = true;
                break;
              }
              store.getState().addFailedOutline(outline);
              options.onSceneFailed?.(outline, actionsResult.error || 'Actions generation failed');
              store.getState().setGenerationStatus('paused');
              pausedByFailureOrAbort = true;
              break;
            }
          }

          if (scene) {
            const settings = useSettingsStore.getState();

            // TTS generation
            if (settings.ttsEnabled && settings.ttsProviderId !== 'browser-native-tts') {
              const ttsResult = await generateTTSForScene(scene, signal);
              if (!ttsResult.success) {
                if (abortRef.current || store.getState().generationEpoch !== startEpoch) {
                  pausedByFailureOrAbort = true;
                  break;
                }
                store.getState().addFailedOutline(outline);
                options.onSceneFailed?.(outline, ttsResult.error || 'TTS generation failed');
                store.getState().setGenerationStatus('paused');
                pausedByFailureOrAbort = true;
                break;
              }
            }

            // Epoch changed — stage switched, discard this scene
            if (store.getState().generationEpoch !== startEpoch) {
              pausedByFailureOrAbort = true;
              break;
            }

            removeGeneratingOutline(outline.id);
            store.getState().addScene(scene);
            options.onSceneGenerated?.(scene, outline.order);
            previousSpeeches = outputPreviousSpeeches;
          }
        }

        if (!abortRef.current && !pausedByFailureOrAbort) {
          store.getState().setGenerationStatus('completed');
          store.getState().setGeneratingOutlines([]);
          options.onComplete?.();
        }
      } catch (err: unknown) {
        // AbortError is expected when stop() is called 鈥?don't treat as failure
        if (err instanceof DOMException && err.name === 'AbortError') {
          log.info('Generation aborted');
          store.getState().setGenerationStatus('paused');
        } else {
          throw err;
        }
      } finally {
        generatingRef.current = false;
        fetchAbortRef.current = null;
      }
    },
    [applyBackendContentToStore, options, store],
  );

  // Keep ref in sync so retrySingleOutline can call it
  generateRemainingRef.current = generateRemaining;

  const stop = useCallback(() => {
    abortRef.current = true;
    store.getState().bumpGenerationEpoch();
    fetchAbortRef.current?.abort();
    mediaAbortRef.current?.abort();
  }, [store]);

  const isGenerating = useCallback(() => generatingRef.current, []);

  /** Retry a single failed outline from scratch (content 鈫?actions 鈫?TTS). */
  const retrySingleOutline = useCallback(
    async (outlineId: string) => {
      const state = store.getState();
      const outline = state.failedOutlines.find((o) => o.id === outlineId);
      const params = lastParamsRef.current;
      if (!outline || !state.stage || !params) return;

      const removeGeneratingOutline = () => {
        const current = store.getState().generatingOutlines;
        if (!current.some((o) => o.id === outlineId)) return;
        store.getState().setGeneratingOutlines(current.filter((o) => o.id !== outlineId));
      };

      // Remove from failed list and mark as generating
      store.getState().retryFailedOutline(outlineId);
      store.getState().setGenerationStatus('generating');
      const currentGenerating = store.getState().generatingOutlines;
      if (!currentGenerating.some((o) => o.id === outline.id)) {
        store.getState().setGeneratingOutlines([...currentGenerating, outline]);
      }

      const abortController = new AbortController();
      const signal = abortController.signal;

      try {
        // Step 1: Content
        const contentResult = await fetchSceneContent(
          {
            outline,
            allOutlines: state.outlines,
            stageId: state.stage.id,
            pdfImages: params.pdfImages,
            imageMapping: params.imageMapping,
            stageInfo: params.stageInfo,
            agents: params.agents,
            outputTypes: params.outputTypes,
            backendSessionId: params.backendSessionId,
            backendReferenceIndex: params.backendReferenceIndex,
            backendReferenceIndexes: params.backendReferenceIndexes,
          },
          signal,
        );

        if (!contentResult.success || !contentResult.content) {
          store.getState().addFailedOutline(outline);
          return;
        }

        if (isBackendCoursewareContent(contentResult.content)) {
          const backendScenes = applyBackendContentToStore(contentResult.content, state.stage.id);
          if (!backendScenes || backendScenes.length === 0) {
            store.getState().addFailedOutline(outline);
          }
          return;
        }

        // Step 2: Actions
        const sortedScenes = [...store.getState().scenes].sort((a, b) => a.order - b.order);
        const lastScene = sortedScenes[sortedScenes.length - 1];
        const previousSpeeches = lastScene
          ? (lastScene.actions || [])
              .filter((a): a is SpeechAction => a.type === 'speech')
              .map((a) => a.text)
          : [];

        const actionsResult = await fetchSceneActions(
          {
            outline: contentResult.effectiveOutline || outline,
            allOutlines: state.outlines,
            content: contentResult.content,
            stageId: state.stage.id,
            agents: params.agents,
            previousSpeeches,
            userProfile: params.userProfile,
          },
          signal,
        );

        if (!actionsResult.success || !actionsResult.scene) {
          store.getState().addFailedOutline(outline);
          return;
        }

        // Step 3: TTS
        const settings = useSettingsStore.getState();
        if (settings.ttsEnabled && settings.ttsProviderId !== 'browser-native-tts') {
          const ttsResult = await generateTTSForScene(actionsResult.scene, signal);
          if (!ttsResult.success) {
            store.getState().addFailedOutline(outline);
            return;
          }
        }

        removeGeneratingOutline();
        store.getState().addScene(actionsResult.scene);

        // Resume remaining generation if there are pending outlines
        if (store.getState().generatingOutlines.length > 0 && lastParamsRef.current) {
          generateRemainingRef.current?.(lastParamsRef.current);
        }
      } catch (err) {
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          store.getState().addFailedOutline(outline);
        }
      }
    },
    [applyBackendContentToStore, store],
  );

  return { generateRemaining, retrySingleOutline, stop, isGenerating };
}
