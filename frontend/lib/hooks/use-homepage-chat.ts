'use client';

import { useState, useCallback, useRef } from 'react';
import { nanoid } from 'nanoid';
import { buildLocalRequirementsFallback } from '@/lib/chat/local-requirements-fallback';
import type { BackendTeachingIntent } from '@/lib/types/backend';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export interface DialogueMetadata {
  state: string;
  isComplete: boolean;
  missingFields: string[];
  collectedInfo: string;
}

type ChatErrorCode =
  | 'CHAT_TIMEOUT'
  | 'BACKEND_FETCH_FAILED'
  | 'UPSTREAM_UNAVAILABLE'
  | 'UPSTREAM_ERROR'
  | 'UNKNOWN';

type ChatError = Error & {
  code?: ChatErrorCode;
};

interface UseHomepageChatReturn {
  messages: ChatMessage[];
  sessionId: string;
  isStreaming: boolean;
  intentCollected: boolean;
  collectedIntent: BackendTeachingIntent | null;
  dialogueMeta: DialogueMetadata | null;
  fallbackMode: boolean;
  sendMessage: (text: string) => Promise<void>;
  resetDialogue: () => void;
}

interface BackendHealthPayload {
  healthy?: boolean;
  backendEnabled?: boolean;
}

function createChatError(message: string, code: ChatErrorCode = 'UNKNOWN'): ChatError {
  const error = new Error(message) as ChatError;
  error.code = code;
  return error;
}

function shouldUseLocalFallback(error: unknown): boolean {
  const code =
    error instanceof Error && 'code' in error && typeof error.code === 'string'
      ? error.code
      : undefined;
  if (code === 'CHAT_TIMEOUT' || code === 'BACKEND_FETCH_FAILED' || code === 'UPSTREAM_UNAVAILABLE') {
    return true;
  }

  const message = error instanceof Error ? error.message.toLowerCase() : String(error ?? '').toLowerCase();
  return (
    message.includes('fetch failed') ||
    message.includes('timed out') ||
    message.includes('stream ended before a reply') ||
    message.includes('dialogue stream failed')
  );
}

function shouldRetryCloudChat(error: unknown, attempt: number): boolean {
  if (attempt >= 1) return false;

  const code =
    error instanceof Error && 'code' in error && typeof error.code === 'string'
      ? error.code
      : undefined;

  if (code === 'CHAT_TIMEOUT' || code === 'BACKEND_FETCH_FAILED' || code === 'UPSTREAM_UNAVAILABLE') {
    return true;
  }

  const message = error instanceof Error ? error.message.toLowerCase() : String(error ?? '').toLowerCase();
  return (
    message.includes('fetch failed') ||
    message.includes('timed out') ||
    message.includes('stream ended before a reply') ||
    message.includes('dialogue stream failed')
  );
}

function toUserFacingChatError(error: unknown): string {
  const rawMessage = error instanceof Error ? error.message : String(error ?? '');
  const message = rawMessage.trim();
  const normalized = message.toLowerCase();

  if (normalized.includes('timed out') || normalized.includes('timeout')) {
    return '对话模型响应超时，请重试。';
  }
  if (normalized.includes('provider unavailable')) {
    return '对话模型服务暂时不可用，请稍后重试。';
  }
  if (normalized.includes('internal server error') || normalized.includes('backend error 500')) {
    return '对话服务异常，请重试。';
  }
  if (message.startsWith('{') && message.endsWith('}')) {
    return '对话服务异常，请重试。';
  }

  return message || '抱歉，对话服务暂时不可用，请稍后重试。';
}

async function readChatFailure(resp: Response): Promise<ChatError> {
  let errorCode: ChatErrorCode = 'UNKNOWN';
  let errorMessage = `Chat failed: ${resp.status}`;

  try {
    const payload = (await resp.json()) as {
      error?: string;
      details?: string;
      errorCode?: string;
    };
    if (typeof payload.errorCode === 'string') {
      errorCode = payload.errorCode as ChatErrorCode;
    }
    errorMessage = payload.details || payload.error || errorMessage;
    return createChatError(errorMessage, errorCode);
  } catch {
    // fall through
  }

  try {
    const textBody = await resp.text();
    if (textBody.trim()) {
      errorMessage = textBody;
    }
  } catch {
    // ignore secondary read failures
  }

  return createChatError(errorMessage, errorCode);
}

/**
 * Lightweight hook for multi-turn dialogue on the homepage.
 * Communicates with the backend dialogue manager via /api/chat SSE proxy.
 */
export function useHomepageChat(): UseHomepageChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [intentCollected, setIntentCollected] = useState(false);
  const [collectedIntent, setCollectedIntent] = useState<BackendTeachingIntent | null>(null);
  const [dialogueMeta, setDialogueMeta] = useState<DialogueMetadata | null>(null);
  const [fallbackMode, setFallbackMode] = useState(false);
  const sessionIdRef = useRef<string>(`dialogue_${nanoid()}`);
  const abortRef = useRef<AbortController | null>(null);
  const backendHealthRef = useRef<{ checkedAt: number; healthy: boolean } | null>(null);
  const consecutiveCloudFailuresRef = useRef(0);

  const ensureBackendHealthy = useCallback(async (): Promise<boolean> => {
    const cached = backendHealthRef.current;
    if (cached && Date.now() - cached.checkedAt < 30_000) {
      return cached.healthy;
    }

    try {
      const resp = await fetch('/api/backend-health', {
        method: 'GET',
        cache: 'no-store',
      });
      if (!resp.ok) {
        backendHealthRef.current = { checkedAt: Date.now(), healthy: false };
        return false;
      }

      const payload = (await resp.json()) as BackendHealthPayload & { success?: boolean };
      const healthy = !!payload.healthy && payload.backendEnabled !== false;
      backendHealthRef.current = { checkedAt: Date.now(), healthy };
      return healthy;
    } catch {
      backendHealthRef.current = { checkedAt: Date.now(), healthy: false };
      return false;
    }
  }, []);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isStreaming) return;

    const trimmedText = text.trim();
    const userMsg: ChatMessage = { id: nanoid(), role: 'user', content: trimmedText };
    const nextHistory = [...messages, userMsg];
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);

    const assistantId = nanoid();
    setMessages((prev) => [...prev, { id: assistantId, role: 'assistant', content: '' }]);

    const controller = new AbortController();
    abortRef.current = controller;
    let receivedMeaningfulReply = false;

    const applyLocalFallback = (banner?: string) => {
      const fallback = buildLocalRequirementsFallback(trimmedText, nextHistory, collectedIntent);
      setFallbackMode(true);
      setIntentCollected(fallback.intentCollected);
      setCollectedIntent(fallback.intent);
      setDialogueMeta(fallback.dialogueMeta);
      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content: [banner, fallback.reply].filter(Boolean).join('\n\n'),
              }
            : message,
        ),
      );
    };

    try {
      const shouldProbeBackend = fallbackMode || consecutiveCloudFailuresRef.current > 0;
      const backendHealthy = shouldProbeBackend ? await ensureBackendHealthy() : true;
      if (shouldProbeBackend && fallbackMode && !backendHealthy && consecutiveCloudFailuresRef.current >= 1) {
        applyLocalFallback('云端对话暂时不稳定，已切换到本地引导模式。');
        return;
      }

      const body = {
        messages: [
          {
            id: nanoid(),
            role: 'user' as const,
            parts: [{ type: 'text' as const, text: trimmedText }],
          },
        ],
        storeState: {
          stage: { id: sessionIdRef.current },
          scenes: [],
          currentSceneId: null,
          mode: 'autonomous',
        },
        config: { agentIds: ['ito-teaching-assistant'] },
      };

      let lastCloudError: unknown = null;

      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: controller.signal,
          });

          if (!resp.ok || !resp.body) {
            throw await readChatFailure(resp);
          }

          const reader = resp.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
              if (!line.startsWith('data: ')) continue;
              const dataStr = line.slice(6).trim();
              if (!dataStr) continue;

              let event: any;
              try {
                event = JSON.parse(dataStr);
              } catch {
                continue;
              }

              if (event.type === 'text_delta' && event.data?.content) {
                receivedMeaningfulReply = true;
                consecutiveCloudFailuresRef.current = 0;
                setFallbackMode(false);
                setMessages((prev) =>
                  prev.map((message) =>
                    message.id === assistantId
                      ? { ...message, content: message.content + event.data.content }
                      : message,
                  ),
                );
                continue;
              }

              if (event.type === 'action') {
                if (event.data?.actionName === 'intent_collected') {
                  setIntentCollected(true);
                  setCollectedIntent(event.data.params as BackendTeachingIntent);
                }
                if (event.data?.actionName === 'dialogue_state') {
                  setDialogueMeta({
                    state: event.data.params?.state || 'collecting',
                    isComplete: !!event.data.params?.is_complete,
                    missingFields: (event.data.params?.missing_fields as string[]) || [],
                    collectedInfo: (event.data.params?.collected_info as string) || '',
                  });
                  if (event.data.params?.is_complete) {
                    setIntentCollected(true);
                  }
                }
                continue;
              }

              if (event.type === 'error') {
                throw createChatError(
                  String(event.data?.message || '对话服务异常，请重试。'),
                  (typeof event.data?.code === 'string' ? event.data.code : 'UNKNOWN') as ChatErrorCode,
                );
              }
            }
          }

          if (!receivedMeaningfulReply) {
            throw createChatError(
              'Dialogue stream ended before a reply was received',
              'BACKEND_FETCH_FAILED',
            );
          }

          lastCloudError = null;
          break;
        } catch (err) {
          if (err instanceof DOMException && err.name === 'AbortError') {
            throw err;
          }

          lastCloudError = err;
          if (!receivedMeaningfulReply && shouldRetryCloudChat(err, attempt)) {
            backendHealthRef.current = null;
            continue;
          }
          throw err;
        }
      }

      if (lastCloudError && !receivedMeaningfulReply) {
        throw lastCloudError;
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;

      if (!receivedMeaningfulReply && shouldUseLocalFallback(err)) {
        consecutiveCloudFailuresRef.current += 1;
        backendHealthRef.current = { checkedAt: Date.now(), healthy: false };

        if (fallbackMode || consecutiveCloudFailuresRef.current >= 2) {
          applyLocalFallback('云端对话暂时不稳定，已切换到本地引导模式。');
          return;
        }

        setMessages((prev) =>
          prev.map((message) =>
            message.id === assistantId
              ? {
                  ...message,
                  content:
                    '这轮云端理解没有稳定完成，我先继续保留云端理解模式。你再发一次或补充一句，我会继续按你的真实需求理解。',
                }
              : message,
          ),
        );
        return;
      }

      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantId && !message.content
            ? { ...message, content: toUserFacingChatError(err) }
            : message,
        ),
      );
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, [collectedIntent, ensureBackendHealthy, fallbackMode, isStreaming, messages]);

  const resetDialogue = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    setMessages([]);
    setIsStreaming(false);
    setIntentCollected(false);
    setCollectedIntent(null);
    setDialogueMeta(null);
    setFallbackMode(false);
    consecutiveCloudFailuresRef.current = 0;
    backendHealthRef.current = null;
    sessionIdRef.current = `dialogue_${nanoid()}`;
  }, []);

  return {
    messages,
    sessionId: sessionIdRef.current,
    isStreaming,
    intentCollected,
    collectedIntent,
    dialogueMeta,
    fallbackMode,
    sendMessage,
    resetDialogue,
  };
}
