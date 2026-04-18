import { create } from 'zustand';
import type { AvatarVisualState, SpeechTask } from '@/components/avatar/types';
import { useSettingsStore } from '@/lib/store/settings';
import { useUserProfileStore } from '@/lib/store/user-profile';

interface AvatarProjectIntroPayload {
  title: string;
  summary: string;
  highlights?: string[];
}

interface AvatarPPTScriptPayload {
  slide_no: number;
  title?: string;
  bullets?: string[];
  speaker_notes?: string;
  summary?: string;
}

interface AvatarResultEventPayload {
  event: string;
  result_level: 'success' | 'warning' | 'error' | 'info';
  summary: string;
  details?: string[];
  next_action?: string;
  slide_no?: number;
}

interface AvatarSessionLoadPayload {
  project_intro: AvatarProjectIntroPayload;
  ppt_scripts: AvatarPPTScriptPayload[];
  result_events?: { events: AvatarResultEventPayload[] };
  metadata?: Record<string, string>;
}

interface AvatarStore {
  // State
  enabled: boolean;
  sessionId: string | null;
  currentTask: SpeechTask | null;
  avatarVisualState: AvatarVisualState;
  subtitle: string | null;
  audioUrl: string | null;
  isSpeaking: boolean;
  hasError: boolean;
  serviceAvailable: boolean;

  // Actions
  setEnabled: (enabled: boolean) => void;
  loadSession: (sessionId: string, payload: AvatarSessionLoadPayload) => Promise<void>;
  triggerProjectIntro: (sessionId: string) => Promise<void>;
  triggerPPTExplain: (sessionId: string, slideNo: number) => Promise<void>;
  triggerBroadcast: (sessionId: string, message: string) => Promise<void>;
  setCurrentTask: (task: SpeechTask) => void;
  reset: () => void;
  checkHealth: () => Promise<boolean>;
}

function sanitizeRuntimeApiKey(input: string): string | null {
  const raw = input.trim();
  if (!raw || raw.length > 4096) return null;
  // Header values must not contain control chars/newlines.
  if (/[\r\n\x00-\x1f\x7f]/.test(raw)) return null;
  // Avoid non-ASCII header values that can trigger HTTP parser 400 in some runtimes.
  if (!/^[\x20-\x7E]+$/.test(raw)) return null;
  return raw;
}

function normalizeRuntimeVlmBaseUrl(input: string): string | null {
  const raw = input.trim();
  if (!raw || raw.length > 2048) return null;
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return null;
    }
    let pathname = parsed.pathname.replace(/\/+$/, '');
    const lowerPath = pathname.toLowerCase();
    // Allow users to paste either API base or full chat/completions endpoint.
    if (lowerPath.endsWith('/chat/completions')) {
      pathname = pathname.slice(0, -'/chat/completions'.length);
    }
    parsed.pathname = pathname || '/';
    parsed.search = '';
    parsed.hash = '';
    return parsed.toString().replace(/\/$/, '');
  } catch {
    return null;
  }
}

function sanitizeRuntimeModelId(input: string): string | null {
  const raw = input.trim();
  if (!raw || raw.length > 128) return null;
  if (/[\r\n\x00-\x1f\x7f]/.test(raw)) return null;
  if (!/^[\x20-\x7E]+$/.test(raw)) return null;
  return raw;
}

function resolveRuntimeVlmConfig():
  | {
      baseUrl: string | null;
      apiKey: string | null;
      model: string | null;
      providerId: string | null;
    }
  | null {
  const profile = useUserProfileStore.getState();
  const settings = useSettingsStore.getState();

  const providerId = settings.providerId;
  const providerConfig = settings.providersConfig?.[providerId];
  const globalApiKey = providerConfig?.apiKey || '';
  const globalBaseUrl =
    providerConfig?.baseUrl || providerConfig?.serverBaseUrl || providerConfig?.defaultBaseUrl || '';
  const globalModel = settings.modelId || '';

  const useGlobal = profile.avatarVlmUseGlobalModelConfig ?? true;

  const rawApiKey = useGlobal ? globalApiKey : profile.avatarVlmApiKey || globalApiKey;
  const rawBaseUrl = useGlobal ? globalBaseUrl : profile.avatarVlmBaseUrl || globalBaseUrl;
  const rawModel = useGlobal ? globalModel : profile.avatarVlmModel || globalModel;

  const apiKey = sanitizeRuntimeApiKey(rawApiKey);
  const baseUrl = normalizeRuntimeVlmBaseUrl(rawBaseUrl);
  const model = sanitizeRuntimeModelId(rawModel);
  const safeProviderId = sanitizeRuntimeModelId(providerId || '');

  if (!apiKey && !baseUrl && !model) {
    return null;
  }

  return {
    apiKey,
    baseUrl,
    model,
    providerId: safeProviderId,
  };
}

function deriveVisualState(task: SpeechTask | null): AvatarVisualState {
  if (!task) return 'idle';
  if (task.status === 'failed' || task.avatar_state === 'error') return 'error';
  if (task.avatar_state === 'paused') return 'paused';
  if (task.avatar_state === 'speaking') {
    if (task.mode === 'project_intro') return 'greet';
    if (task.mode === 'result_broadcast') return 'notify';
    return 'explain';
  }
  return 'idle';
}

function rewriteAudioUrl(url: string | null): string | null {
  if (!url) return null;
  // Rewrite backend media paths to go through our proxy
  // /media/cache/xxx.mp3 → /api/avatar/media/cache/xxx.mp3
  if (url.startsWith('/media/')) {
    return `/api/avatar${url}`;
  }
  return url;
}

function buildAvatarHeaders(
  includeJson: boolean,
  options?: {
    includeRuntimeVlm?: boolean;
  },
): HeadersInit {
  const headers: Record<string, string> = {};
  if (includeJson) {
    headers['Content-Type'] = 'application/json';
  }
  const includeRuntimeVlm = options?.includeRuntimeVlm ?? true;
  if (includeRuntimeVlm) {
    const vlmConfig = resolveRuntimeVlmConfig();
    if (vlmConfig?.baseUrl) {
      headers['x-avatar-vlm-base-url'] = vlmConfig.baseUrl;
    }
    if (vlmConfig?.apiKey) {
      headers['x-avatar-vlm-api-key'] = vlmConfig.apiKey;
    }
    if (vlmConfig?.model) {
      headers['x-avatar-vlm-model'] = vlmConfig.model;
    }
    if (vlmConfig?.providerId) {
      headers['x-avatar-vlm-provider'] = vlmConfig.providerId;
    }
  }
  return headers;
}

async function avatarFetch<T>(path: string, body?: object): Promise<T> {
  const opts: RequestInit = {
    method: body ? 'POST' : 'GET',
    headers: buildAvatarHeaders(Boolean(body)),
    body: body ? JSON.stringify(body) : undefined,
  };
  const resp = await fetch(`/api/avatar/${path}`, opts);
  if (!resp.ok) {
    throw new Error(`Avatar API error ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export const useAvatarStore = create<AvatarStore>((set, get) => ({
  enabled: true,
  sessionId: null,
  currentTask: null,
  avatarVisualState: 'idle',
  subtitle: null,
  audioUrl: null,
  isSpeaking: false,
  hasError: false,
  serviceAvailable: false,

  setEnabled: (enabled) => set({ enabled }),

  checkHealth: async () => {
    try {
      const resp = await fetch('/api/avatar/health', {
        signal: AbortSignal.timeout(3000),
        headers: buildAvatarHeaders(false, { includeRuntimeVlm: false }),
      });
      if (!resp.ok) {
        throw new Error(`Avatar health check failed: ${resp.status}`);
      }
      set({ serviceAvailable: true, enabled: true, hasError: false });
      return true;
    } catch {
      set({ serviceAvailable: false, enabled: false });
      return false;
    }
  },

  loadSession: async (sessionId, payload) => {
    try {
      await avatarFetch('session/load', {
        session_id: sessionId,
        ...payload,
        result_events: payload.result_events || { events: [] },
      });
      set({ sessionId, hasError: false });
    } catch {
      set({ hasError: true });
    }
  },

  triggerProjectIntro: async (sessionId) => {
    try {
      const task = await avatarFetch<SpeechTask>('project-intro', { session_id: sessionId });
      get().setCurrentTask(task);
    } catch {
      set({ hasError: true });
    }
  },

  triggerPPTExplain: async (sessionId, slideNo) => {
    try {
      const task = await avatarFetch<SpeechTask>('ppt-explain', {
        session_id: sessionId,
        slide_no: slideNo,
      });
      get().setCurrentTask(task);
    } catch {
      set({ hasError: true });
    }
  },

  triggerBroadcast: async (sessionId, message) => {
    try {
      const task = await avatarFetch<SpeechTask>('broadcast', {
        session_id: sessionId,
        event: message,
      });
      get().setCurrentTask(task);
    } catch {
      // Graceful fallback: keep user message visible even when avatar backend fails.
      set({
        hasError: true,
        subtitle: message,
        audioUrl: null,
        isSpeaking: false,
      });
    }
  },

  setCurrentTask: (task) => {
    const visualState = deriveVisualState(task);
    set({
      currentTask: task,
      avatarVisualState: visualState,
      subtitle: task.subtitle || null,
      audioUrl: rewriteAudioUrl(task.audio_url),
      isSpeaking: task.avatar_state === 'speaking',
      hasError: task.status === 'failed',
    });
  },

  reset: () =>
    set({
      sessionId: null,
      currentTask: null,
      avatarVisualState: 'idle',
      subtitle: null,
      audioUrl: null,
      isSpeaking: false,
      hasError: false,
    }),
}));
