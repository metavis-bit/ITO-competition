import { NextRequest } from 'next/server';
import { transcribeAudio } from '@/lib/audio/asr-providers';
import { resolveASRApiKey, resolveASRBaseUrl } from '@/lib/server/provider-config';
import type { ASRProviderId } from '@/lib/audio/types';
import { createLogger } from '@/lib/logger';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { validateUrlForSSRF } from '@/lib/server/ssrf-guard';
const log = createLogger('Transcription');

export const maxDuration = 60;

function normalizeAudioFormat(raw: string | null): string | null {
  if (!raw) return null;
  const v = raw.trim().toLowerCase();
  if (!v) return null;
  if (v.includes('/')) {
    if (v.includes('webm')) return 'webm';
    if (v.includes('mp4') || v.includes('m4a')) return 'm4a';
    if (v.includes('mpeg') || v.includes('mp3')) return 'mp3';
    if (v.includes('wav')) return 'wav';
    if (v.includes('flac')) return 'flac';
    if (v.includes('ogg')) return 'ogg';
    return null;
  }
  const direct = v.replace(/^\./, '');
  if (['webm', 'm4a', 'mp3', 'wav', 'flac', 'ogg', 'mp4', 'mpeg', 'mpga'].includes(direct)) {
    if (direct === 'mp4' || direct === 'mpeg' || direct === 'mpga') return direct === 'mp4' ? 'm4a' : 'mp3';
    return direct;
  }
  return null;
}

function detectAudioFormat(audioFile: File, explicitFormat: string | null): string | undefined {
  const fromExplicit = normalizeAudioFormat(explicitFormat);
  if (fromExplicit) return fromExplicit;

  const fromMime = normalizeAudioFormat(audioFile.type || null);
  if (fromMime) return fromMime;

  const lowerName = (audioFile.name || '').toLowerCase();
  const ext = lowerName.includes('.') ? lowerName.slice(lowerName.lastIndexOf('.') + 1) : '';
  const fromName = normalizeAudioFormat(ext);
  return fromName || undefined;
}

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();
    const audioFile = formData.get('audio') as File;
    const providerId = formData.get('providerId') as ASRProviderId | null;
    const language = formData.get('language') as string | null;
    const apiKey = formData.get('apiKey') as string | null;
    const baseUrl = formData.get('baseUrl') as string | null;
    const format = formData.get('format') as string | null;

    if (!audioFile) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'Audio file is required');
    }

    // providerId is required from the client — no server-side store to fall back to
    const effectiveProviderId = providerId || ('openai-whisper' as ASRProviderId);

    const clientBaseUrl = baseUrl || undefined;
    if (clientBaseUrl && process.env.NODE_ENV === 'production') {
      const ssrfError = validateUrlForSSRF(clientBaseUrl);
      if (ssrfError) {
        return apiError('INVALID_URL', 403, ssrfError);
      }
    }

    const config = {
      providerId: effectiveProviderId,
      language: language || 'auto',
      apiKey: clientBaseUrl
        ? apiKey || ''
        : resolveASRApiKey(effectiveProviderId, apiKey || undefined),
      baseUrl: clientBaseUrl
        ? clientBaseUrl
        : resolveASRBaseUrl(effectiveProviderId, baseUrl || undefined),
      format: detectAudioFormat(audioFile, format),
    };

    // Convert audio file to buffer
    const arrayBuffer = await audioFile.arrayBuffer();
    const buffer = Buffer.from(arrayBuffer);

    // Transcribe using the provider system (with provider fallback for better stability).
    let result;
    try {
      result = await transcribeAudio(config, buffer);
    } catch (primaryError) {
      const shouldFallbackToOpenAI = effectiveProviderId === 'qwen-asr';
      if (!shouldFallbackToOpenAI) {
        throw primaryError;
      }

      const fallbackProviderId = 'openai-whisper' as ASRProviderId;
      const fallbackApiKey = resolveASRApiKey(fallbackProviderId, undefined);
      if (!fallbackApiKey) {
        throw primaryError;
      }

      const fallbackConfig = {
        ...config,
        providerId: fallbackProviderId,
        apiKey: fallbackApiKey,
        baseUrl: resolveASRBaseUrl(fallbackProviderId, undefined),
      };

      try {
        log.warn('Primary ASR failed, retrying with fallback provider openai-whisper');
        result = await transcribeAudio(fallbackConfig, buffer);
      } catch (fallbackError) {
        const primaryMsg = primaryError instanceof Error ? primaryError.message : String(primaryError);
        const fallbackMsg = fallbackError instanceof Error ? fallbackError.message : String(fallbackError);
        throw new Error(`ASR failed on primary and fallback providers. primary=${primaryMsg}; fallback=${fallbackMsg}`);
      }
    }

    return apiSuccess({ text: result.text });
  } catch (error) {
    log.error('Transcription error:', error);
    return apiError(
      'TRANSCRIPTION_FAILED',
      500,
      'Transcription failed',
      error instanceof Error ? error.message : 'Unknown error',
    );
  }
}
