/**
 * Backend Proxy — routes core generation requests to FastAPI backend.
 *
 * Strategy:
 *   - If BACKEND_URL is set and BACKEND_ENABLED=true, proxy to FastAPI
 *   - Otherwise, fall through to original OpenMaic logic
 *   - TTS/image/video generation always stay client-side (not proxied)
 */

import type { BackendArtifact, BackendPlanData } from '@/lib/types/backend-courseware';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:9527';
const BACKEND_ENABLED = process.env.BACKEND_ENABLED === 'true';

export function isBackendEnabled(): boolean {
  return BACKEND_ENABLED && !!BACKEND_URL;
}

export function getBackendUrl(path: string): string {
  const base = BACKEND_URL.replace(/\/$/, '');
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return `${base}${cleanPath}`;
}

/**
 * Proxy a JSON POST request to the FastAPI backend.
 */
export async function proxyJsonPost<T = unknown>(
  path: string,
  body: object,
  options?: {
    signal?: AbortSignal;
    timeout?: number;
  },
): Promise<T> {
  const url = getBackendUrl(path);
  const controller = new AbortController();
  const timeout = options?.timeout ?? 120_000;

  const timeoutId = setTimeout(() => controller.abort(), timeout);

  // Merge abort signals
  if (options?.signal) {
    options.signal.addEventListener('abort', () => controller.abort());
  }

  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!resp.ok) {
      const errorText = await resp.text().catch(() => 'Unknown error');
      throw new Error(`Backend error ${resp.status}: ${errorText}`);
    }

    return (await resp.json()) as T;
  } catch (error) {
    if (controller.signal.aborted && !options?.signal?.aborted) {
      throw new Error(`Backend request timed out after ${timeout}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Proxy a multipart/form-data POST request to the FastAPI backend.
 * Keep Content-Type unset so fetch can attach boundary automatically.
 */
export async function proxyFormPost<T = unknown>(
  path: string,
  formData: FormData,
  options?: {
    signal?: AbortSignal;
    timeout?: number;
  },
): Promise<T> {
  const url = getBackendUrl(path);
  const controller = new AbortController();
  const timeout = options?.timeout ?? 120_000;

  const timeoutId = setTimeout(() => controller.abort(), timeout);

  if (options?.signal) {
    options.signal.addEventListener('abort', () => controller.abort());
  }

  try {
    const resp = await fetch(url, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });

    if (!resp.ok) {
      const errorText = await resp.text().catch(() => 'Unknown error');
      throw new Error(`Backend error ${resp.status}: ${errorText}`);
    }

    return (await resp.json()) as T;
  } catch (error) {
    if (controller.signal.aborted && !options?.signal?.aborted) {
      throw new Error(`Backend request timed out after ${timeout}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}
/**
 * Proxy a streaming (SSE) POST request to the FastAPI backend.
 * Returns a ReadableStream that can be used directly in a Response.
 */
export function proxyStreamPost(
  path: string,
  body: object,
  options?: {
    signal?: AbortSignal;
    transformEvent?: (event: BackendSSEEvent) => string | null;
  },
): ReadableStream<Uint8Array> {
  const url = getBackendUrl(path);
  const encoder = new TextEncoder();

  return new ReadableStream({
    async start(controller) {
      try {
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: options?.signal,
        });

        if (!resp.ok || !resp.body) {
          const errorText = await resp.text().catch(() => 'Unknown error');
          const errorEvent = `data: ${JSON.stringify({ type: 'error', error: errorText })}\n\n`;
          controller.enqueue(encoder.encode(errorEvent));
          controller.close();
          return;
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
            if (line.startsWith('data: ')) {
              const dataStr = line.slice(6).trim();
              if (!dataStr) continue;

              try {
                const event = JSON.parse(dataStr) as BackendSSEEvent;
                if (options?.transformEvent) {
                  const transformed = options.transformEvent(event);
                  if (transformed !== null) {
                    controller.enqueue(encoder.encode(`data: ${transformed}\n\n`));
                  }
                } else {
                  controller.enqueue(encoder.encode(`${line}\n\n`));
                }
              } catch {
                // Pass through non-JSON lines
                controller.enqueue(encoder.encode(`${line}\n\n`));
              }
            } else if (line.startsWith(':')) {
              // Pass through comments (heartbeat)
              controller.enqueue(encoder.encode(`${line}\n`));
            }
          }
        }

        controller.close();
      } catch (err) {
        const msg =
          err instanceof Error && err.name === 'AbortError' && !options?.signal?.aborted
            ? 'Backend stream request timed out'
            : err instanceof Error
              ? err.message
              : 'Unknown proxy error';
        const errorEvent = `data: ${JSON.stringify({ type: 'error', error: msg })}\n\n`;
        controller.enqueue(encoder.encode(errorEvent));
        controller.close();
      }
    },
  });
}

// ── Backend SSE Event Types ──

export interface BackendSSEEvent {
  event: string;
  data: Record<string, unknown>;
}

// ── Backend Request/Response Types ──

export interface BackendGenerateRequest {
  session_id?: string;
  topic: string;
  subject?: string;
  target_audience?: string;
  teaching_goal?: string;
  grade_level?: string;
  page_range?: string;
  key_focus?: string[];
  difficulties?: string[];
  game_types?: string[];
  special_requirements?: string;
  indexes?: string[];
  output_types?: string[];
}

export interface BackendStreamRequest {
  session_id?: string;
  topic: string;
  subject?: string;
  target_audience?: string;
  teaching_goal?: string;
  grade_level?: string;
  page_range?: string;
  key_focus?: string[];
  difficulties?: string[];
  game_types?: string[];
  special_requirements?: string;
  indexes?: string[];
}

export interface BackendGenerateResponse {
  session_id: string;
  version_id: string | null;
  artifacts: BackendArtifact[];
  errors: string[];
  total_time_sec: number;
  plan?: BackendPlanData;
}

export interface BackendIngestRequest {
  dir_path: string;
  index?: string;
  session_id?: string;
}

/**
 * Proxy a GET request to the FastAPI backend.
 */
export async function proxyGet<T = unknown>(
  path: string,
  options?: {
    signal?: AbortSignal;
    timeout?: number;
  },
): Promise<T> {
  const url = getBackendUrl(path);
  const controller = new AbortController();
  const timeout = options?.timeout ?? 30_000;

  const timeoutId = setTimeout(() => controller.abort(), timeout);

  if (options?.signal) {
    options.signal.addEventListener('abort', () => controller.abort());
  }

  try {
    const resp = await fetch(url, {
      method: 'GET',
      signal: controller.signal,
    });

    if (!resp.ok) {
      const errorText = await resp.text().catch(() => 'Unknown error');
      throw new Error(`Backend error ${resp.status}: ${errorText}`);
    }

    return (await resp.json()) as T;
  } finally {
    clearTimeout(timeoutId);
  }
}



