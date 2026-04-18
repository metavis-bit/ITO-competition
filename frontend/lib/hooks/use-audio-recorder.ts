import { useState, useRef, useCallback } from 'react';
import { createLogger } from '@/lib/logger';
import { ASR_PROVIDERS } from '@/lib/audio/constants';

const log = createLogger('AudioRecorder');

// TypeScript declarations for Web Speech API
declare global {
  interface Window {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Web Speech API not typed in lib.dom
    SpeechRecognition: any;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Web Speech API not typed in lib.dom
    webkitSpeechRecognition: any;
  }
}

export interface UseAudioRecorderOptions {
  onTranscription?: (text: string) => void;
  onError?: (error: string) => void;
}

const TRANSCRIPTION_MAX_RETRIES = 2;

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function shouldRetryTranscription(status: number | null, message: string): boolean {
  if (status != null && (status === 408 || status === 429 || status >= 500)) {
    return true;
  }
  return /fetch failed|network|timeout|timed out|aborted/i.test(message);
}

function normalizeMimeType(mimeType?: string | null): string {
  if (!mimeType) return 'audio/webm';
  return mimeType.split(';')[0].trim().toLowerCase() || 'audio/webm';
}

function mimeTypeToFormat(mimeType?: string | null): string {
  const normalized = normalizeMimeType(mimeType);
  if (normalized === 'audio/webm') return 'webm';
  if (normalized === 'audio/mp4' || normalized === 'audio/m4a' || normalized === 'video/mp4') {
    return 'm4a';
  }
  if (normalized === 'audio/mpeg' || normalized === 'audio/mp3') return 'mp3';
  if (normalized === 'audio/wav' || normalized === 'audio/x-wav' || normalized === 'audio/wave') {
    return 'wav';
  }
  if (normalized === 'audio/flac') return 'flac';
  if (normalized === 'audio/ogg') return 'ogg';
  return 'webm';
}

function pickMediaRecorderMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return undefined;
  }
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
    'audio/ogg',
  ];
  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate));
}

export function useAudioRecorder(options: UseAudioRecorderOptions = {}) {
  const { onTranscription, onError } = options;

  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingMimeTypeRef = useRef<string>('audio/webm');
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Web Speech API not typed
  const speechRecognitionRef = useRef<any>(null);

  // Send audio to server for transcription
  const transcribeAudio = useCallback(
    async (audioBlob: Blob, recordedMimeType?: string) => {
      setIsProcessing(true);

      try {
        const formData = new FormData();
        const mimeType = normalizeMimeType(recordedMimeType || audioBlob.type || recordingMimeTypeRef.current);
        const format = mimeTypeToFormat(mimeType);
        formData.append('audio', audioBlob, `recording.${format}`);
        formData.append('format', format);

        // Get current ASR configuration from settings store
        // Note: This requires importing useSettingsStore in browser context
        if (typeof window !== 'undefined') {
          const { useSettingsStore } = await import('@/lib/store/settings');
          const { asrProviderId, asrLanguage, asrProvidersConfig } = useSettingsStore.getState();

          formData.append('providerId', asrProviderId);
          formData.append('language', asrLanguage);

          // Append API key and base URL if configured
          const providerConfig = asrProvidersConfig?.[asrProviderId];
          if (providerConfig?.apiKey?.trim()) {
            formData.append('apiKey', providerConfig.apiKey);
          }
          if (providerConfig?.baseUrl?.trim()) {
            formData.append('baseUrl', providerConfig.baseUrl);
          }
        }

        let attempt = 0;
        let lastError: Error | null = null;
        while (attempt <= TRANSCRIPTION_MAX_RETRIES) {
          let status: number | null = null;
          try {
            const response = await fetch('/api/transcription', {
              method: 'POST',
              body: formData,
            });
            status = response.status;

            if (!response.ok) {
              const payload = (await response.json().catch(() => null)) as
                | { error?: string; details?: string; message?: string }
                | null;
              const message =
                payload?.details || payload?.error || payload?.message || 'Transcription failed';
              throw new Error(message);
            }

            const result = (await response.json().catch(() => ({}))) as { text?: string };
            onTranscription?.(result.text || '');
            return;
          } catch (error) {
            const message = error instanceof Error ? error.message : 'Transcription failed';
            lastError = error instanceof Error ? error : new Error(message);

            if (attempt < TRANSCRIPTION_MAX_RETRIES && shouldRetryTranscription(status, message)) {
              attempt += 1;
              log.warn(`Transcription retry #${attempt} after error: ${message}`);
              await wait(250 * attempt);
              continue;
            }
            throw lastError;
          }
        }

        throw lastError || new Error('Transcription failed');
      } catch (error) {
        log.error('Transcription error:', error);
        onError?.(error instanceof Error ? error.message : '语音识别失败，请重试');
      } finally {
        setIsProcessing(false);
        setRecordingTime(0);
      }
    },
    [onTranscription, onError],
  );

  // Start recording
  const startRecording = useCallback(async () => {
    try {
      // Get current ASR configuration
      if (typeof window !== 'undefined') {
        const { useSettingsStore } = await import('@/lib/store/settings');
        const { asrProviderId, asrLanguage, asrProvidersConfig } = useSettingsStore.getState();

        // Determine effective provider: fall back to browser-native when the
        // configured server-side provider requires an API key but none is available
        // (neither from client settings nor from server config).
        const providerDef = ASR_PROVIDERS[asrProviderId];
        const providerCfg = asrProvidersConfig?.[asrProviderId];
        const hasClientKey = !!providerCfg?.apiKey?.trim();
        const hasServerKey = !!providerCfg?.isServerConfigured;

        // Use browser native ASR if configured (or fell back to it)
        if (asrProviderId === 'browser-native') {
          // Check if Speech Recognition is supported
          if (!window.SpeechRecognition && !window.webkitSpeechRecognition) {
            onError?.('您的浏览器不支持语音识别功能');
            return;
          }

          const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
          const recognition = new SpeechRecognition();

          recognition.lang = asrLanguage || 'zh-CN';
          recognition.continuous = false;
          recognition.interimResults = false;

          recognition.onstart = () => {
            setIsRecording(true);
            setRecordingTime(0);

            // Start timer
            timerRef.current = setInterval(() => {
              setRecordingTime((prev) => prev + 1);
            }, 1000);
          };

          recognition.onresult = (event: {
            results: {
              [index: number]: { [index: number]: { transcript: string } };
            };
          }) => {
            const transcript = event.results[0][0].transcript;
            onTranscription?.(transcript);
          };

          recognition.onerror = (event: { error: string }) => {
            log.error('Speech recognition error:', event.error);
            let errorMessage = '语音识别失败';

            switch (event.error) {
              case 'no-speech':
                errorMessage = '未检测到语音输入';
                break;
              case 'audio-capture':
                errorMessage = '无法访问麦克风';
                break;
              case 'not-allowed':
                errorMessage = '麦克风权限被拒绝';
                break;
              case 'network':
                errorMessage = '网络错误';
                break;
              default:
                errorMessage = `语音识别错误: ${event.error}`;
            }

            onError?.(errorMessage);
            setIsRecording(false);
            setRecordingTime(0);
            if (timerRef.current) {
              clearInterval(timerRef.current);
              timerRef.current = null;
            }
          };

          recognition.onend = () => {
            setIsRecording(false);
            setRecordingTime(0);
            if (timerRef.current) {
              clearInterval(timerRef.current);
              timerRef.current = null;
            }
          };

          recognition.start();
          speechRecognitionRef.current = recognition;
          return;
        }

        if (providerDef?.requiresApiKey && !hasClientKey && !hasServerKey) {
          log.error(
            `ASR provider "${asrProviderId}" is selected but no client/server credentials were found`,
          );
          onError?.('当前 ASR 配置无效，请检查服务端或设置页中的转写 Provider 配置');
          return;
        }
      }

      // Use MediaRecorder for server-side ASR
      // Request microphone permission
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferredMimeType = pickMediaRecorderMimeType();

      // Create MediaRecorder
      const mediaRecorder = preferredMimeType
        ? new MediaRecorder(stream, { mimeType: preferredMimeType })
        : new MediaRecorder(stream);

      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];
      recordingMimeTypeRef.current = normalizeMimeType(mediaRecorder.mimeType || preferredMimeType);

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        // Stop all audio tracks
        stream.getTracks().forEach((track) => track.stop());

        const firstChunkType = audioChunksRef.current.find((chunk) => chunk.type)?.type;
        const finalMimeType = normalizeMimeType(firstChunkType || recordingMimeTypeRef.current);

        // Merge audio chunks
        const audioBlob = new Blob(audioChunksRef.current, {
          type: finalMimeType,
        });

        // Send to server for transcription
        await transcribeAudio(audioBlob, finalMimeType);
      };

      // Start recording
      mediaRecorder.start();
      setIsRecording(true);
      setRecordingTime(0);

      // Start timer
      timerRef.current = setInterval(() => {
        setRecordingTime((prev) => prev + 1);
      }, 1000);
    } catch (error) {
      log.error('Failed to start recording:', error);
      onError?.('无法访问麦克风，请检查权限设置');
    }
  }, [onTranscription, onError, transcribeAudio]);

  // Stop recording
  const stopRecording = useCallback(() => {
    // Stop Speech Recognition if active
    if (speechRecognitionRef.current) {
      speechRecognitionRef.current.stop();
      speechRecognitionRef.current = null;
      setIsRecording(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    // Stop MediaRecorder if active
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);

      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
  }, [isRecording]);

  // Cancel recording
  const cancelRecording = useCallback(() => {
    // Cancel Speech Recognition if active
    if (speechRecognitionRef.current) {
      speechRecognitionRef.current.onresult = null; // Prevent transcription callback
      speechRecognitionRef.current.stop();
      speechRecognitionRef.current = null;
      setIsRecording(false);
      setRecordingTime(0);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    // Cancel MediaRecorder if active
    if (mediaRecorderRef.current && isRecording) {
      // Stop recording without transcription
      mediaRecorderRef.current.ondataavailable = null;
      mediaRecorderRef.current.onstop = null;
      mediaRecorderRef.current.stop();

      // Stop all audio tracks
      if (mediaRecorderRef.current.stream) {
        mediaRecorderRef.current.stream.getTracks().forEach((track) => track.stop());
      }

      setIsRecording(false);
      setRecordingTime(0);

      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }

      audioChunksRef.current = [];
      recordingMimeTypeRef.current = 'audio/webm';
    }
  }, [isRecording]);

  return {
    isRecording,
    isProcessing,
    recordingTime,
    startRecording,
    stopRecording,
    cancelRecording,
  };
}
