/**
 * Stateless Chat API Endpoint
 *
 * POST /api/chat - Send message, receive SSE stream
 *
 * This endpoint:
 * 1. Receives full state from client (messages + storeState)
 * 2. Runs single-pass generation
 * 3. Streams events as SSE (text deltas + tool calls)
 *
 * Fully stateless: interruption is handled by the client aborting
 * the fetch request, which triggers req.signal on the server side.
 */

import { NextRequest } from 'next/server';
import { statelessGenerate } from '@/lib/orchestration/stateless-generate';
import type { StatelessChatRequest, StatelessEvent } from '@/lib/types/chat';
import type { ThinkingConfig } from '@/lib/types/provider';
import { apiError } from '@/lib/server/api-response';
import { createLogger } from '@/lib/logger';
import { resolveModel } from '@/lib/server/resolve-model';
import { isBackendEnabled, getBackendUrl } from '@/lib/server/backend-proxy';
import type { BackendChatRequest } from '@/lib/types/backend';
const log = createLogger('Chat API');

// Allow streaming responses up to 60 seconds
export const maxDuration = 60;

/**
 * POST /api/chat
 * Send a message and receive SSE stream of generation events
 *
 * Request body: StatelessChatRequest
 * {
 *   messages: UIMessage[],
 *   storeState: { stage, scenes, currentSceneId, mode },
 *   config: { agentIds, sessionType? },
 *   apiKey: string,
 *   baseUrl?: string,
 *   model?: string
 * }
 *
 * Response: SSE stream of StatelessEvent
 */
export async function POST(req: NextRequest) {
  const encoder = new TextEncoder();
  const BACKEND_CHAT_TIMEOUT_MS = 40_000;

  try {
    const body: StatelessChatRequest = await req.json();

    // ── Backend proxy mode ──
    if (isBackendEnabled()) {
      const lastUserMsg = [...(body.messages || [])].reverse().find((m) => m.role === 'user');
      const messageText = lastUserMsg
        ? (lastUserMsg.parts || [])
            .filter((p): p is { type: 'text'; text: string } => p.type === 'text')
            .map((p) => p.text)
            .join('\n')
        : '';
      const sessionType = body.config?.sessionType || 'requirements';
      if (!messageText && sessionType === 'requirements') {
        return apiError('MISSING_REQUIRED_FIELD', 400, 'No user message found');
      }

      // Derive a stable session id from the stage when available
      const stageId = (body.storeState?.stage as Record<string, unknown> | null)?.id;
      const sessionId = stageId ? `stage_${String(stageId)}` : undefined;

      const backendBody: BackendChatRequest = {
        session_id: sessionId,
        message: messageText,
        session_type: sessionType,
        discussion_topic: body.config?.discussionTopic,
        discussion_prompt: body.config?.discussionPrompt,
        trigger_agent_id: body.config?.triggerAgentId,
        agent_ids: body.config?.agentIds || [],
        agent_configs: body.config?.agentConfigs as Array<Record<string, unknown>> | undefined,
        messages: (body.messages || []).map((m) => ({
          role: m.role,
          parts: m.parts,
          metadata: m.metadata || {},
        })),
        user_profile: body.userProfile || {},
      };

      const backendUrl = getBackendUrl('/v1/chat');
      const backendController = new AbortController();
      const timeoutId = setTimeout(() => backendController.abort('chat-timeout'), BACKEND_CHAT_TIMEOUT_MS);
      req.signal.addEventListener('abort', () => backendController.abort('client-abort'));

      let backendResp: Response;
      try {
        backendResp = await fetch(backendUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(backendBody),
          signal: backendController.signal,
        });
      } catch (error) {
        clearTimeout(timeoutId);
        if (backendController.signal.aborted && !req.signal.aborted) {
          return apiError(
            'CHAT_TIMEOUT',
            504,
            'Chat timed out',
            `Dialogue timed out after ${Math.floor(BACKEND_CHAT_TIMEOUT_MS / 1000)} seconds`,
          );
        }
        if (error instanceof TypeError) {
          log.error('Backend chat proxy fetch failed:', error);
          return apiError(
            'BACKEND_FETCH_FAILED',
            503,
            'Backend chat connection failed',
            error.message || 'fetch failed',
          );
        }
        throw error;
      }

      clearTimeout(timeoutId);

      if (!backendResp.ok || !backendResp.body) {
        let errText = 'Backend error';
        try {
          const rawText = await backendResp.text();
          if (rawText) {
            try {
              const parsed = JSON.parse(rawText) as {
                detail?: string;
                details?: string;
                error?: string;
              };
              errText = parsed.detail || parsed.details || parsed.error || rawText;
            } catch {
              errText = rawText;
            }
          }
        } catch {
          // keep fallback
        }
        log.error('Backend chat proxy error:', errText);
        const errorCode =
          backendResp.status === 503 || backendResp.status === 504
            ? 'UPSTREAM_UNAVAILABLE'
            : 'UPSTREAM_ERROR';
        return apiError(errorCode, backendResp.status, errText);
      }

      // Transform backend SSE (CHAT_REPLY / AGENT_REPLY) → frontend SSE (StatelessEvent)
      const sseEncoder = new TextEncoder();
      const legacyMessageId = crypto.randomUUID();
      const legacyAgentId = 'ito-teaching-assistant';
      const legacyAgentName = 'ITO 教学助手';

      const proxyStream = new ReadableStream({
        async start(controller) {
          const reader = backendResp.body!.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          let sentLegacyStart = false;
          let totalAgents = 0;
          let agentHadContent = false;

          const emit = (event: StatelessEvent) => {
            controller.enqueue(sseEncoder.encode(`data: ${JSON.stringify(event)}\n\n`));
          };

          try {
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

                try {
                  const event = JSON.parse(dataStr);

                  if (event.event === 'ERROR') {
                    emit({
                      type: 'error',
                      data: {
                        code:
                          typeof event.data?.code === 'string'
                            ? event.data.code
                            : 'UPSTREAM_UNAVAILABLE',
                        message:
                          typeof event.data?.message === 'string'
                            ? event.data.message
                            : 'Dialogue stream failed',
                      },
                    });
                    continue;
                  }

                  if (event.event === 'CHAT_REPLY_DELTA') {
                    if (!sentLegacyStart) {
                      emit({
                        type: 'agent_start',
                        data: {
                          messageId: legacyMessageId,
                          agentId: legacyAgentId,
                          agentName: legacyAgentName,
                        },
                      });
                      sentLegacyStart = true;
                      totalAgents = Math.max(totalAgents, 1);
                    }

                    const textContent = String(event.data?.content || '');
                    if (textContent.trim()) {
                      agentHadContent = true;
                    }
                    emit({
                      type: 'text_delta',
                      data: { content: textContent, messageId: legacyMessageId },
                    });
                    continue;
                  }

                  if (event.event === 'CHAT_REPLY') {
                    // Emit agent_start on first reply
                    if (!sentLegacyStart) {
                      emit({
                        type: 'agent_start',
                        data: {
                          messageId: legacyMessageId,
                          agentId: legacyAgentId,
                          agentName: legacyAgentName,
                        },
                      });
                      sentLegacyStart = true;
                      totalAgents = Math.max(totalAgents, 1);
                    }

                    // Emit text content
                    const textContent = String(event.data?.message || '');
                    if (textContent.trim()) {
                      agentHadContent = true;
                    }
                    emit({
                      type: 'text_delta',
                      data: { content: textContent, messageId: legacyMessageId },
                    });

                    // Emit dialogue state so frontend can track collection progress
                    if (event.data.state) {
                      emit({
                        type: 'action',
                        data: {
                          actionId: crypto.randomUUID(),
                          actionName: 'dialogue_state',
                          params: {
                            state: event.data.state,
                            is_complete: event.data.is_complete ?? false,
                            missing_fields: event.data.missing_fields ?? [],
                            collected_info: event.data.collected_info ?? '',
                          },
                          agentId: legacyAgentId,
                          messageId: legacyMessageId,
                        },
                      });
                    }

                    // Emit agent_end
                    emit({
                      type: 'agent_end',
                      data: { messageId: legacyMessageId, agentId: legacyAgentId },
                    });
                  }

                  if (event.event === 'AGENT_REPLY') {
                    const replyData = (event.data || {}) as Record<string, unknown>;
                    const roleMessageId = crypto.randomUUID();
                    const roleAgentId = String(replyData.agent_id || 'classroom-agent');
                    const roleAgentName = String(replyData.agent_name || roleAgentId);
                    const roleMessage = String(replyData.message || '');
                    const roleAvatar =
                      typeof replyData.agent_avatar === 'string' ? replyData.agent_avatar : undefined;
                    const roleColor =
                      typeof replyData.agent_color === 'string' ? replyData.agent_color : undefined;

                    totalAgents += 1;
                    if (roleMessage.trim()) {
                      agentHadContent = true;
                    }

                    emit({
                      type: 'agent_start',
                      data: {
                        messageId: roleMessageId,
                        agentId: roleAgentId,
                        agentName: roleAgentName,
                        agentAvatar: roleAvatar,
                        agentColor: roleColor,
                      },
                    });

                    emit({
                      type: 'text_delta',
                      data: { content: roleMessage, messageId: roleMessageId },
                    });

                    emit({
                      type: 'agent_end',
                      data: { messageId: roleMessageId, agentId: roleAgentId },
                    });
                  }

                  if (event.event === 'CUE_USER') {
                    const cueData = (event.data || {}) as Record<string, unknown>;
                    emit({
                      type: 'cue_user',
                      data: {
                        fromAgentId:
                          typeof cueData.from_agent_id === 'string'
                            ? cueData.from_agent_id
                            : undefined,
                        prompt: typeof cueData.prompt === 'string' ? cueData.prompt : undefined,
                      },
                    });
                  }

                  if (event.event === 'INTENT_COLLECTED') {
                    // Surface intent as an action so the frontend can react
                    emit({
                      type: 'action',
                      data: {
                        actionId: crypto.randomUUID(),
                        actionName: 'intent_collected',
                        params: event.data.intent || {},
                        agentId: legacyAgentId,
                        messageId: legacyMessageId,
                      },
                    });
                  }
                } catch {
                  // skip non-JSON lines
                }
              }
            }

            // Emit done
            emit({
              type: 'done',
              data: { totalActions: 0, totalAgents, agentHadContent },
            });
            controller.close();
          } catch (err) {
            emit({
              type: 'error',
              data: {
                code: err instanceof Error && err.message.toLowerCase().includes('timeout')
                  ? 'CHAT_TIMEOUT'
                  : 'BACKEND_FETCH_FAILED',
                message: err instanceof Error ? err.message : 'Backend proxy error',
              },
            });
            controller.close();
          }
        },
      });

      return new Response(proxyStream, {
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
        },
      });
    }

    // Validate required fields
    if (!body.messages || !Array.isArray(body.messages)) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'Missing required field: messages');
    }

    if (!body.storeState) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'Missing required field: storeState');
    }

    if (!body.config || !body.config.agentIds || body.config.agentIds.length === 0) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'Missing required field: config.agentIds');
    }

    const { model: languageModel, apiKey: resolvedApiKey } = resolveModel({
      modelString: body.model,
      apiKey: body.apiKey,
      baseUrl: body.baseUrl,
      providerType: body.providerType,
      requiresApiKey: body.requiresApiKey,
    });

    if (!resolvedApiKey && body.requiresApiKey !== false) {
      return apiError('MISSING_API_KEY', 401, 'API Key is required');
    }

    log.info('Processing request');
    log.info(
      `Agents: ${body.config.agentIds.join(', ')}, Messages: ${body.messages.length}, Turn: ${body.directorState?.turnCount ?? 0}`,
    );

    // Use the native request signal for abort propagation
    const signal = req.signal;

    // Create SSE stream
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();

    // Stream generation in background with heartbeat to prevent connection timeout
    const HEARTBEAT_INTERVAL_MS = 15_000;
    (async () => {
      // Heartbeat: periodically send SSE comments to keep the connection alive.
      // Proxies / browsers may close idle SSE connections after 30-120s of silence.
      let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
      const startHeartbeat = () => {
        stopHeartbeat();
        heartbeatTimer = setInterval(() => {
          try {
            writer.write(encoder.encode(`:heartbeat\n\n`)).catch(() => stopHeartbeat());
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

      try {
        startHeartbeat();

        const generator = statelessGenerate(
          {
            ...body,
            apiKey: resolvedApiKey,
          },
          signal,
          languageModel,
          { enabled: false } satisfies ThinkingConfig,
        );

        for await (const event of generator) {
          if (signal.aborted) {
            log.info('Request was aborted');
            break;
          }

          const data = `data: ${JSON.stringify(event)}\n\n`;
          await writer.write(encoder.encode(data));
        }

        stopHeartbeat();
        await writer.close();
      } catch (error) {
        stopHeartbeat();

        // If aborted, just close the writer silently
        if (signal.aborted) {
          log.info('Request aborted during streaming');
          try {
            await writer.close();
          } catch {
            /* already closed */
          }
          return;
        }

        log.error('Stream error:', error);

        // Try to send error event
        try {
          const errorEvent: StatelessEvent = {
            type: 'error',
            data: {
              message: error instanceof Error ? error.message : String(error),
            },
          };
          await writer.write(encoder.encode(`data: ${JSON.stringify(errorEvent)}\n\n`));
          await writer.close();
        } catch {
          // Writer may already be closed
        }
      }
    })();

    return new Response(readable, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
    });
  } catch (error) {
    log.error('Error:', error);
    return apiError(
      'INTERNAL_ERROR',
      500,
      error instanceof Error ? error.message : 'Failed to process request',
    );
  }
}
