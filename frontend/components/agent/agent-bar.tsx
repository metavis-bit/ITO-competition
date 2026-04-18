'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Checkbox } from '@/components/ui/checkbox';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { useI18n } from '@/lib/hooks/use-i18n';
import { useSettingsStore } from '@/lib/store/settings';
import { useAgentRegistry } from '@/lib/orchestration/registry/store';
import { resolveAgentVoice, getAvailableProvidersWithVoices } from '@/lib/audio/voice-resolver';
import { playBrowserTTSPreview } from '@/lib/audio/browser-tts-preview';
import {
  Sparkles,
  ChevronDown,
  ChevronUp,
  Shuffle,
  Volume2,
  VolumeX,
  Loader2,
  MessageSquare,
  Minus,
  Plus,
  BrainCircuit,
  PencilLine,
  RotateCcw,
} from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { AgentConfig } from '@/lib/orchestration/registry/types';
import type { TTSProviderId } from '@/lib/audio/types';
import type { ProviderWithVoices } from '@/lib/audio/voice-resolver';
import { resolveRoleLLMConfig } from '@/lib/orchestration/role-llm';
import type { ProviderId } from '@/lib/types/provider';

interface LLMModelOption {
  id: string;
  name?: string;
}

interface LLMProviderOption {
  name?: string;
  models?: LLMModelOption[];
}

function pickDefaultModelId(provider?: LLMProviderOption): string | undefined {
  return provider?.models?.[0]?.id;
}

function getProviderOptions(
  providersConfig: Partial<Record<ProviderId, LLMProviderOption>>,
): Array<LLMProviderOption & { id: ProviderId }> {
  return Object.entries(providersConfig)
    .map(([id, cfg]) => ({
      id: id as ProviderId,
      name: cfg?.name || id,
      models: Array.isArray(cfg?.models) ? cfg.models : [],
    }))
    .filter((provider) => provider.models && provider.models.length > 0)
    .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
}

function AgentLLMPill({
  agent,
  providersConfig,
  globalProviderId,
  globalModelId,
}: {
  agent: AgentConfig;
  providersConfig: Partial<Record<ProviderId, LLMProviderOption>>;
  globalProviderId: ProviderId;
  globalModelId: string;
}) {
  const updateAgent = useAgentRegistry((s) => s.updateAgent);
  const [open, setOpen] = useState(false);
  const providerOptions = getProviderOptions(providersConfig);

  const resolved = resolveRoleLLMConfig({
    role: agent.role,
    providerId: globalProviderId,
    modelId: globalModelId,
    providersConfig,
    preferredProviderId: agent.llmConfig?.providerId,
    preferredModelId: agent.llmConfig?.modelId,
  });
  const hasOverride = Boolean(agent.llmConfig?.providerId || agent.llmConfig?.modelId);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          className="flex items-center gap-1 h-5 max-w-[112px] rounded-full bg-violet-500/10 hover:bg-violet-500/20 px-2 text-[10px] text-violet-700 dark:text-violet-300 transition-colors shrink-0"
          title={`${resolved.providerName} / ${resolved.modelId}`}
        >
          <BrainCircuit className="size-2.5 shrink-0" />
          <span className="truncate">
            {resolved.providerName}
            {hasOverride ? '*' : ''}
          </span>
          <ChevronDown className="size-2.5 shrink-0 opacity-60" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="end"
        sideOffset={4}
        className="w-56 p-1 max-h-72 overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={() => {
            updateAgent(agent.id, { llmConfig: undefined });
            setOpen(false);
          }}
          className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-muted flex items-center gap-1.5"
        >
          <RotateCcw className="size-3" />
          跟随角色默认
        </button>
        <div className="my-1 border-t border-border/50" />
        {providerOptions.map((provider) => {
          const modelId = pickDefaultModelId(provider) || resolved.modelId;
          const active =
            resolved.providerId === provider.id &&
            (agent.llmConfig?.providerId === provider.id || !agent.llmConfig?.providerId);
          return (
            <button
              key={provider.id}
              type="button"
              onClick={() => {
                updateAgent(agent.id, {
                  llmConfig: {
                    providerId: provider.id,
                    modelId,
                  },
                });
                setOpen(false);
              }}
              className={cn(
                'w-full text-left text-xs px-2 py-1.5 rounded hover:bg-muted',
                active && 'bg-violet-500/10 text-violet-700 dark:text-violet-300',
              )}
            >
              <div className="font-medium truncate">{provider.name || provider.id}</div>
              <div className="text-[10px] text-muted-foreground truncate">{modelId}</div>
            </button>
          );
        })}
      </PopoverContent>
    </Popover>
  );
}

function AgentPersonaPill({ agent }: { agent: AgentConfig }) {
  const updateAgent = useAgentRegistry((s) => s.updateAgent);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(agent.persona || '');

  return (
    <Popover
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (nextOpen) {
          setDraft(agent.persona || '');
        }
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          className="flex items-center gap-1 h-5 rounded-full bg-emerald-500/10 hover:bg-emerald-500/20 px-2 text-[10px] text-emerald-700 dark:text-emerald-300 transition-colors shrink-0"
          title="编辑角色 Prompt"
        >
          <PencilLine className="size-2.5 shrink-0" />
          <span>Prompt</span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="end"
        sideOffset={4}
        className="w-72 p-2"
        onClick={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <div className="text-[11px] font-medium text-muted-foreground mb-1">角色 Prompt</div>
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="输入该角色的人设、语气和行为约束..."
          className="min-h-[120px] text-xs"
        />
        <div className="mt-2 flex justify-end gap-2">
          <button
            type="button"
            className="px-2 py-1 text-xs rounded border hover:bg-muted"
            onClick={() => {
              setDraft(agent.persona || '');
              setOpen(false);
            }}
          >
            取消
          </button>
          <button
            type="button"
            className="px-2 py-1 text-xs rounded bg-primary text-primary-foreground hover:opacity-90"
            onClick={() => {
              updateAgent(agent.id, { persona: draft.trim() || agent.persona });
              setOpen(false);
            }}
          >
            保存
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function AgentVoicePill({
  agent,
  agentIndex,
  availableProviders,
  disabled,
}: {
  agent: AgentConfig;
  agentIndex: number;
  availableProviders: ProviderWithVoices[];
  disabled?: boolean;
}) {
  const updateAgent = useAgentRegistry((s) => s.updateAgent);
  const ttsProvidersConfig = useSettingsStore((s) => s.ttsProvidersConfig);
  const resolved = resolveAgentVoice(agent, agentIndex, availableProviders);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [previewingId, setPreviewingId] = useState<string | null>(null);
  const previewCancelRef = useRef<(() => void) | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);

  const displayName = (() => {
    for (const p of availableProviders) {
      if (p.providerId === resolved.providerId) {
        const v = p.voices.find((voice) => voice.id === resolved.voiceId);
        if (v) return v.name;
      }
    }
    return resolved.voiceId;
  })();

  const stopPreview = useCallback(() => {
    previewCancelRef.current?.();
    previewCancelRef.current = null;
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current.src = '';
      previewAudioRef.current = null;
    }
    setPreviewingId(null);
  }, []);

  const handlePreview = useCallback(
    async (providerId: TTSProviderId, voiceId: string) => {
      const key = `${providerId}::${voiceId}`;
      if (previewingId === key) {
        stopPreview();
        return;
      }
      stopPreview();
      setPreviewingId(key);

      const courseLanguage =
        (typeof localStorage !== 'undefined' && localStorage.getItem('generationLanguage')) ||
        'zh-CN';
      const previewText = courseLanguage === 'en-US' ? 'Welcome to Ruijie Cloud Classroom' : '欢迎使用锐捷云课堂';

      if (providerId === 'browser-native-tts') {
        const { promise, cancel } = playBrowserTTSPreview({ text: previewText, voice: voiceId });
        previewCancelRef.current = cancel;
        try {
          await promise;
        } catch {
          // ignore abort
        }
        setPreviewingId(null);
        return;
      }

      // Server TTS
      try {
        const controller = new AbortController();
        previewAbortRef.current = controller;
        const providerConfig = ttsProvidersConfig[providerId];
        const res = await fetch('/api/generate/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: previewText,
            audioId: 'voice-preview',
            ttsProviderId: providerId,
            ttsVoice: voiceId,
            ttsSpeed: 1,
            ttsApiKey: providerConfig?.apiKey,
            ttsBaseUrl: providerConfig?.serverBaseUrl || providerConfig?.baseUrl,
          }),
          signal: controller.signal,
        });
        if (!res.ok) throw new Error('TTS error');
        const data = await res.json();
        if (!data.base64) throw new Error('No audio');

        const audio = new Audio(`data:audio/${data.format || 'mp3'};base64,${data.base64}`);
        previewAudioRef.current = audio;
        audio.addEventListener('ended', () => setPreviewingId(null));
        audio.addEventListener('error', () => setPreviewingId(null));
        await audio.play();
      } catch {
        setPreviewingId(null);
      }
    },
    [previewingId, stopPreview, ttsProvidersConfig],
  );

  // Cleanup on unmount
  useEffect(() => () => stopPreview(), [stopPreview]);

  if (disabled) {
    return (
      <div
        onClick={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
        className="flex items-center gap-1 h-5 w-[88px] rounded-full bg-muted/40 px-2 text-[10px] text-muted-foreground/30 shrink-0 cursor-not-allowed"
      >
        <VolumeX className="size-2.5 shrink-0" />
        <span className="truncate flex-1 text-left">{displayName}</span>
      </div>
    );
  }

  return (
    <Popover
      open={popoverOpen}
      onOpenChange={(open) => {
        setPopoverOpen(open);
        if (!open) stopPreview();
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          className="flex items-center gap-1 h-5 w-[88px] rounded-full bg-primary/10 hover:bg-primary/20 dark:bg-primary/25 dark:hover:bg-primary/35 px-2 text-[10px] text-primary/80 hover:text-primary dark:text-primary/90 transition-colors shrink-0 cursor-pointer"
        >
          <Volume2 className="size-2.5 shrink-0" />
          <span className="truncate flex-1 text-left">{displayName}</span>
          <ChevronDown className="size-2.5 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="end"
        sideOffset={4}
        className="w-52 px-1 pb-1 pt-0 max-h-64 overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
      >
        {availableProviders.map((provider) => (
          <div key={provider.providerId}>
            <div className="text-[10px] text-muted-foreground/60 font-medium px-2 py-1 sticky top-0 bg-popover">
              {provider.providerName}
            </div>
            {provider.voices.map((voice) => {
              const isActive =
                resolved.providerId === provider.providerId && resolved.voiceId === voice.id;
              const previewKey = `${provider.providerId}::${voice.id}`;
              const isPreviewing = previewingId === previewKey;
              return (
                <div
                  key={previewKey}
                  className={cn(
                    'flex items-center gap-1 rounded-sm transition-colors',
                    isActive ? 'bg-primary/10' : 'hover:bg-muted',
                  )}
                >
                  <button
                    type="button"
                    onClick={() => {
                      updateAgent(agent.id, {
                        voiceConfig: { providerId: provider.providerId, voiceId: voice.id },
                      });
                      setPopoverOpen(false);
                    }}
                    className={cn(
                      'flex-1 text-left text-xs px-2 py-1 min-w-0 truncate',
                      isActive ? 'text-primary font-medium' : 'text-foreground',
                    )}
                  >
                    {voice.name}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handlePreview(provider.providerId, voice.id);
                    }}
                    className={cn(
                      'shrink-0 size-5 flex items-center justify-center rounded-sm transition-colors',
                      isPreviewing
                        ? 'text-primary'
                        : 'text-muted-foreground/40 hover:text-muted-foreground',
                    )}
                  >
                    {isPreviewing ? (
                      <Loader2 className="size-3 animate-spin" />
                    ) : (
                      <Volume2 className="size-3" />
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </PopoverContent>
    </Popover>
  );
}

/**
 * Teacher voice pill — reads/writes global ttsProviderId + ttsVoice (single source of truth).
 * This ensures lecture and discussion use the same voice for the teacher.
 */
function TeacherVoicePill({
  availableProviders,
  disabled,
}: {
  availableProviders: ProviderWithVoices[];
  disabled?: boolean;
}) {
  const ttsProviderId = useSettingsStore((s) => s.ttsProviderId);
  const ttsVoice = useSettingsStore((s) => s.ttsVoice);
  const setTTSProvider = useSettingsStore((s) => s.setTTSProvider);
  const setTTSVoice = useSettingsStore((s) => s.setTTSVoice);
  const ttsProvidersConfig = useSettingsStore((s) => s.ttsProvidersConfig);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [previewingId, setPreviewingId] = useState<string | null>(null);
  const previewCancelRef = useRef<(() => void) | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);

  const displayName = (() => {
    for (const p of availableProviders) {
      if (p.providerId === ttsProviderId) {
        const v = p.voices.find((voice) => voice.id === ttsVoice);
        if (v) return v.name;
      }
    }
    return ttsVoice || 'default';
  })();

  const stopPreview = useCallback(() => {
    previewCancelRef.current?.();
    previewCancelRef.current = null;
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current.src = '';
      previewAudioRef.current = null;
    }
    setPreviewingId(null);
  }, []);

  const handlePreview = useCallback(
    async (providerId: TTSProviderId, voiceId: string) => {
      const key = `${providerId}::${voiceId}`;
      if (previewingId === key) {
        stopPreview();
        return;
      }
      stopPreview();
      setPreviewingId(key);

      const courseLanguage =
        (typeof localStorage !== 'undefined' && localStorage.getItem('generationLanguage')) ||
        'zh-CN';
      const previewText = courseLanguage === 'en-US' ? 'Welcome to Ruijie Cloud Classroom' : '欢迎使用锐捷云课堂';

      if (providerId === 'browser-native-tts') {
        const { promise, cancel } = playBrowserTTSPreview({ text: previewText, voice: voiceId });
        previewCancelRef.current = cancel;
        try {
          await promise;
        } catch {
          // ignore abort
        }
        setPreviewingId(null);
        return;
      }

      try {
        const controller = new AbortController();
        previewAbortRef.current = controller;
        const providerConfig = ttsProvidersConfig[providerId];
        const res = await fetch('/api/generate/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: previewText,
            audioId: 'voice-preview',
            ttsProviderId: providerId,
            ttsVoice: voiceId,
            ttsSpeed: 1,
            ttsApiKey: providerConfig?.apiKey,
            ttsBaseUrl: providerConfig?.serverBaseUrl || providerConfig?.baseUrl,
          }),
          signal: controller.signal,
        });
        if (!res.ok) throw new Error('TTS error');
        const data = await res.json();
        if (!data.base64) throw new Error('No audio');
        const audio = new Audio(`data:audio/${data.format || 'mp3'};base64,${data.base64}`);
        previewAudioRef.current = audio;
        audio.addEventListener('ended', () => setPreviewingId(null));
        audio.addEventListener('error', () => setPreviewingId(null));
        await audio.play();
      } catch {
        setPreviewingId(null);
      }
    },
    [previewingId, stopPreview, ttsProvidersConfig],
  );

  useEffect(() => () => stopPreview(), [stopPreview]);

  if (disabled) {
    return (
      <div
        onClick={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
        className="flex items-center gap-1 h-5 w-[88px] rounded-full bg-muted/40 px-2 text-[10px] text-muted-foreground/30 shrink-0 cursor-not-allowed"
      >
        <VolumeX className="size-2.5 shrink-0" />
        <span className="truncate flex-1 text-left">{displayName}</span>
      </div>
    );
  }

  return (
    <Popover
      open={popoverOpen}
      onOpenChange={(open) => {
        setPopoverOpen(open);
        if (!open) stopPreview();
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          className="flex items-center gap-1 h-5 w-[88px] rounded-full bg-primary/10 hover:bg-primary/20 dark:bg-primary/25 dark:hover:bg-primary/35 px-2 text-[10px] text-primary/80 hover:text-primary dark:text-primary/90 transition-colors shrink-0 cursor-pointer"
        >
          <Volume2 className="size-2.5 shrink-0" />
          <span className="truncate flex-1 text-left">{displayName}</span>
          <ChevronDown className="size-2.5 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="end"
        sideOffset={4}
        className="w-52 px-1 pb-1 pt-0 max-h-64 overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
      >
        {availableProviders.map((provider) => (
          <div key={provider.providerId}>
            <div className="text-[10px] text-muted-foreground/60 font-medium px-2 py-1 sticky top-0 bg-popover">
              {provider.providerName}
            </div>
            {provider.voices.map((voice) => {
              const isActive = ttsProviderId === provider.providerId && ttsVoice === voice.id;
              const previewKey = `${provider.providerId}::${voice.id}`;
              const isPreviewing = previewingId === previewKey;
              return (
                <div
                  key={previewKey}
                  className={cn(
                    'flex items-center gap-1 rounded-sm transition-colors',
                    isActive ? 'bg-primary/10' : 'hover:bg-muted',
                  )}
                >
                  <button
                    type="button"
                    onClick={() => {
                      setTTSProvider(provider.providerId);
                      setTTSVoice(voice.id);
                      setPopoverOpen(false);
                    }}
                    className={cn(
                      'flex-1 text-left text-xs px-2 py-1 min-w-0 truncate',
                      isActive ? 'text-primary font-medium' : 'text-foreground',
                    )}
                  >
                    {voice.name}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handlePreview(provider.providerId, voice.id);
                    }}
                    className={cn(
                      'shrink-0 size-5 flex items-center justify-center rounded-sm transition-colors',
                      isPreviewing
                        ? 'text-primary'
                        : 'text-muted-foreground/40 hover:text-muted-foreground',
                    )}
                  >
                    {isPreviewing ? (
                      <Loader2 className="size-3 animate-spin" />
                    ) : (
                      <Volume2 className="size-3" />
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </PopoverContent>
    </Popover>
  );
}

export function AgentBar() {
  const { t } = useI18n();
  const { listAgents } = useAgentRegistry();
  const selectedAgentIds = useSettingsStore((s) => s.selectedAgentIds);
  const setSelectedAgentIds = useSettingsStore((s) => s.setSelectedAgentIds);
  const maxTurns = useSettingsStore((s) => s.maxTurns);
  const setMaxTurns = useSettingsStore((s) => s.setMaxTurns);
  const agentMode = useSettingsStore((s) => s.agentMode);
  const setAgentMode = useSettingsStore((s) => s.setAgentMode);
  const providerId = useSettingsStore((s) => s.providerId);
  const modelId = useSettingsStore((s) => s.modelId);
  const providersConfig = useSettingsStore((s) => s.providersConfig);
  const ttsProvidersConfig = useSettingsStore((s) => s.ttsProvidersConfig);
  const ttsEnabled = useSettingsStore((s) => s.ttsEnabled);

  const [open, setOpen] = useState(false);
  const [browserVoices, setBrowserVoices] = useState<SpeechSynthesisVoice[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  // Load browser native TTS voices
  useEffect(() => {
    if (typeof window === 'undefined' || !window.speechSynthesis) return;
    const loadVoices = () => setBrowserVoices(speechSynthesis.getVoices());
    loadVoices();
    speechSynthesis.addEventListener('voiceschanged', loadVoices);
    return () => speechSynthesis.removeEventListener('voiceschanged', loadVoices);
  }, []);

  const allAgents = listAgents();
  const agents = allAgents.filter((a) => !a.isGenerated);
  const teacherAgent = agents.find((a) => a.role === 'teacher');
  const selectedAgents = agents.filter((a) => selectedAgentIds.includes(a.id));
  const nonTeacherSelected = selectedAgents.filter((a) => a.role !== 'teacher');

  const serverProviders = getAvailableProvidersWithVoices(ttsProvidersConfig);
  const availableProviders: ProviderWithVoices[] = [
    ...serverProviders,
    ...(browserVoices.length > 0
      ? [
          {
            providerId: 'browser-native-tts' as TTSProviderId,
            providerName: 'Browser Native',
            voices: browserVoices.map((v) => ({ id: v.voiceURI, name: v.name })),
          },
        ]
      : []),
  ];
  const showVoice = availableProviders.length > 0;
  const teacherLLM = teacherAgent
    ? resolveRoleLLMConfig({
        role: teacherAgent.role,
        providerId,
        modelId,
        providersConfig,
        preferredProviderId: teacherAgent.llmConfig?.providerId,
        preferredModelId: teacherAgent.llmConfig?.modelId,
      })
    : null;

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (containerRef.current && containerRef.current.contains(target)) return;
      // Don't close if clicking inside a Radix portal (Popover, Select, etc.)
      if ((target as Element).closest?.('[data-radix-popper-content-wrapper]')) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleModeChange = (mode: 'preset' | 'auto') => {
    setAgentMode(mode);
    if (mode === 'preset') {
      const hasTeacherSelected = selectedAgentIds.some((id) => {
        const a = agents.find((agent) => agent.id === id);
        return a?.role === 'teacher';
      });
      if (!hasTeacherSelected && teacherAgent) {
        setSelectedAgentIds([teacherAgent.id, ...selectedAgentIds]);
      }
    }
  };

  const toggleAgent = (agentId: string) => {
    const agent = agents.find((a) => a.id === agentId);
    if (agent?.role === 'teacher') return;
    if (selectedAgentIds.includes(agentId)) {
      setSelectedAgentIds(selectedAgentIds.filter((id) => id !== agentId));
    } else {
      setSelectedAgentIds([...selectedAgentIds, agentId]);
    }
  };

  const getAgentName = (agent: { id: string; name: string }) => {
    const key = `settings.agentNames.${agent.id}`;
    const translated = t(key);
    return translated !== key ? translated : agent.name;
  };

  const getAgentRole = (agent: { role: string }) => {
    const key = `settings.agentRoles.${agent.role}`;
    const translated = t(key);
    return translated !== key ? translated : agent.role;
  };

  const avatarRow = (
    <div className="flex items-center gap-1.5 shrink-0">
      {teacherAgent && (
        <div className="size-8 rounded-full overflow-hidden ring-2 ring-blue-400/40 dark:ring-blue-500/30 shrink-0">
          <img
            src={teacherAgent.avatar}
            alt={getAgentName(teacherAgent)}
            className="size-full object-cover"
          />
        </div>
      )}

      {agentMode === 'auto' ? (
        <>
          <div className="flex -space-x-2">
            {agents.find((a) => a.role === 'assistant') && (
              <div className="size-6 rounded-full overflow-hidden ring-[1.5px] ring-background">
                <img
                  src={agents.find((a) => a.role === 'assistant')!.avatar}
                  alt=""
                  className="size-full object-cover"
                />
              </div>
            )}
          </div>
          <Shuffle className="size-4 text-violet-400 dark:text-violet-500" />
        </>
      ) : (
        <>
          {nonTeacherSelected.length > 0 && (
            <div className="flex -space-x-2">
              {nonTeacherSelected.slice(0, 4).map((agent) => (
                <div
                  key={agent.id}
                  className="size-6 rounded-full overflow-hidden ring-[1.5px] ring-background"
                >
                  <img
                    src={agent.avatar}
                    alt={getAgentName(agent)}
                    className="size-full object-cover"
                  />
                </div>
              ))}
              {nonTeacherSelected.length > 4 && (
                <div className="size-6 rounded-full bg-muted ring-[1.5px] ring-background flex items-center justify-center">
                  <span className="text-[9px] font-bold text-muted-foreground">
                    +{nonTeacherSelected.length - 4}
                  </span>
                </div>
              )}
            </div>
          )}
        </>
      )}
      {showVoice &&
        (ttsEnabled ? (
          <Volume2 className="size-3.5 text-muted-foreground/40 group-hover:text-muted-foreground/60 transition-colors" />
        ) : (
          <VolumeX className="size-3.5 text-muted-foreground/30" />
        ))}
    </div>
  );

  const renderAgentRow = (agent: AgentConfig, agentIndex: number, isTeacher: boolean) => {
    const isSelected = isTeacher || selectedAgentIds.includes(agent.id);
    const llm = resolveRoleLLMConfig({
      role: agent.role,
      providerId,
      modelId,
      providersConfig,
      preferredProviderId: agent.llmConfig?.providerId,
      preferredModelId: agent.llmConfig?.modelId,
    });
    return (
      <div
        key={agent.id}
        onClick={isTeacher ? undefined : () => toggleAgent(agent.id)}
        className={cn(
          'w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg transition-colors',
          isTeacher ? 'bg-primary/5' : 'cursor-pointer',
          !isTeacher && isSelected && 'bg-primary/5',
          !isTeacher && !isSelected && 'hover:bg-muted/50',
        )}
      >
        <Checkbox
          checked={isSelected}
          disabled={isTeacher}
          className={cn('pointer-events-none', isTeacher && 'opacity-50')}
        />
        <div
          className="size-7 rounded-full overflow-hidden shrink-0 ring-1 ring-border/40"
          style={{ boxShadow: isSelected ? `0 0 0 2px ${agent.color}30` : undefined }}
        >
          <img src={agent.avatar} alt={getAgentName(agent)} className="size-full object-cover" />
        </div>
        <span className="text-[13px] font-medium truncate min-w-0 flex-1">
          {getAgentName(agent)}
        </span>
        <div className="shrink-0 w-[110px] text-right leading-tight">
          <div className="text-[10px] text-muted-foreground/50">{getAgentRole(agent)}</div>
          <div className="text-[9px] text-primary/70 truncate" title={llm.modelId}>
            {llm.providerName}
          </div>
        </div>
        <AgentLLMPill
          agent={agent}
          providersConfig={providersConfig}
          globalProviderId={providerId}
          globalModelId={modelId}
        />
        <AgentPersonaPill agent={agent} />
        {showVoice && (
          <AgentVoicePill
            agent={agent}
            agentIndex={agentIndex}
            availableProviders={availableProviders}
            disabled={!ttsEnabled}
          />
        )}
      </div>
    );
  };

  return (
    <div ref={containerRef} className="relative w-96">
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            className={cn(
              'group flex items-center gap-2 cursor-pointer rounded-full px-2.5 py-2 transition-all w-full',
              'border border-border/50 text-muted-foreground/70 hover:text-foreground hover:bg-muted/60',
            )}
            onClick={() => setOpen(!open)}
          >
            <span className="text-xs text-muted-foreground/60 group-hover:text-muted-foreground transition-colors hidden sm:block font-medium flex-1 text-left truncate">
              {open ? t('agentBar.expandedTitle') : t('agentBar.readyToLearn')}
            </span>
            {avatarRow}
            {open ? (
              <ChevronUp className="size-3 text-muted-foreground/40 group-hover:text-muted-foreground/70 transition-colors" />
            ) : (
              <ChevronDown className="size-3 text-muted-foreground/40 group-hover:text-muted-foreground/70 transition-colors" />
            )}
          </button>
        </TooltipTrigger>
        {!open && (
          <TooltipContent side="bottom" sideOffset={4}>
            {t('agentBar.configTooltip')}
          </TooltipContent>
        )}
      </Tooltip>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.97 }}
            transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
            className="absolute right-0 top-full mt-1 z-50 w-96"
          >
            <div className="rounded-2xl bg-white/95 dark:bg-slate-800/95 backdrop-blur-sm ring-1 ring-black/[0.04] dark:ring-white/[0.06] shadow-[0_1px_8px_-2px_rgba(0,0,0,0.06)] dark:shadow-[0_1px_8px_-2px_rgba(0,0,0,0.3)] px-2 py-1.5">
              {/* Teacher — always visible */}
              {teacherAgent && (
                <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-primary/5 mb-2">
                  <div
                    className="size-7 rounded-full overflow-hidden shrink-0 ring-1 ring-border/40"
                    style={{ boxShadow: `0 0 0 2px ${teacherAgent.color}30` }}
                  >
                    <img
                      src={teacherAgent.avatar}
                      alt={getAgentName(teacherAgent)}
                      className="size-full object-cover"
                    />
                  </div>
                  <span className="text-[13px] font-medium truncate min-w-0 flex-1">
                    {getAgentName(teacherAgent)}
                  </span>
                  {teacherLLM && (
                    <span
                      className="text-[9px] px-2 py-0.5 rounded-full bg-primary/8 text-primary/80"
                      title={teacherLLM.modelId}
                    >
                      {teacherLLM.providerName}
                    </span>
                  )}
                  <AgentLLMPill
                    agent={teacherAgent}
                    providersConfig={providersConfig}
                    globalProviderId={providerId}
                    globalModelId={modelId}
                  />
                  <AgentPersonaPill agent={teacherAgent} />
                  {showVoice && (
                    <TeacherVoicePill
                      availableProviders={availableProviders}
                      disabled={!ttsEnabled}
                    />
                  )}
                </div>
              )}

              {/* Mode tabs */}
              <div className="flex rounded-lg border bg-muted/30 p-0.5 mb-2">
                <button
                  onClick={() => handleModeChange('preset')}
                  className={cn(
                    'flex-1 py-1.5 text-xs font-medium rounded-md transition-all text-center',
                    agentMode === 'preset'
                      ? 'bg-background shadow-sm text-foreground'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {t('settings.agentModePreset')}
                </button>
                <button
                  onClick={() => handleModeChange('auto')}
                  className={cn(
                    'flex-1 py-1.5 text-xs font-medium rounded-md transition-all text-center flex items-center justify-center gap-1',
                    agentMode === 'auto'
                      ? 'bg-background shadow-sm text-foreground'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <Sparkles className="h-3 w-3" />
                  {t('settings.agentModeAuto')}
                </button>
              </div>

              {agentMode === 'preset' ? (
                <div className="max-h-56 overflow-y-auto -mx-0.5">
                  {agents
                    .filter((a) => a.role !== 'teacher')
                    .map((agent, idx) => renderAgentRow(agent, idx + 1, false))}
                </div>
              ) : (
                <div className="flex flex-col items-center pt-6 pb-3 gap-4">
                  <div className="relative flex items-center justify-center">
                    <div className="absolute size-10 rounded-full bg-violet-400/10 dark:bg-violet-400/15 animate-ping [animation-duration:3s]" />
                    <div className="absolute size-12 rounded-full bg-violet-400/5 dark:bg-violet-400/10 animate-pulse [animation-duration:2.5s]" />
                    <Shuffle className="relative size-5 text-violet-400 dark:text-violet-500" />
                  </div>
                  <div className="flex-1" />
                  <div className="text-center space-y-1">
                    <p className="text-[11px] text-muted-foreground/60">
                      {t('settings.agentModeAutoDesc')}
                    </p>
                    <p className="text-[10px] text-muted-foreground/40">
                      {t('agentBar.voiceAutoAssign')}
                    </p>
                  </div>
                </div>
              )}

              {/* Max turns — compact stepper */}
              <div className="flex items-center gap-1.5 px-2 py-1 mt-1 border-t border-border/30">
                <MessageSquare className="size-3 text-muted-foreground/40 shrink-0" />
                <span className="text-[11px] text-muted-foreground/50 flex-1">
                  {t('settings.maxTurns')}
                </span>
                <div className="flex items-center rounded-full bg-muted/50 h-5 shrink-0">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      const v = Math.max(1, parseInt(maxTurns || '1') - 1);
                      setMaxTurns(String(v));
                    }}
                    className="size-5 flex items-center justify-center text-muted-foreground/60 hover:text-foreground transition-colors rounded-full hover:bg-muted"
                  >
                    <Minus className="size-2.5" />
                  </button>
                  <input
                    type="text"
                    inputMode="numeric"
                    value={maxTurns}
                    onChange={(e) => {
                      const raw = e.target.value.replace(/\D/g, '');
                      if (!raw) {
                        setMaxTurns('');
                        return;
                      }
                      const v = Math.min(20, Math.max(1, parseInt(raw)));
                      setMaxTurns(String(v));
                    }}
                    onBlur={() => {
                      if (!maxTurns || parseInt(maxTurns) < 1) setMaxTurns('1');
                    }}
                    onClick={(e) => e.stopPropagation()}
                    className="w-5 h-5 text-[11px] font-medium tabular-nums text-center bg-transparent outline-none border-none"
                  />
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      const v = Math.min(20, parseInt(maxTurns || '1') + 1);
                      setMaxTurns(String(v));
                    }}
                    className="size-5 flex items-center justify-center text-muted-foreground/60 hover:text-foreground transition-colors rounded-full hover:bg-muted"
                  >
                    <Plus className="size-2.5" />
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
