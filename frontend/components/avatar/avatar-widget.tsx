'use client';

import { useState, useEffect, useRef } from 'react';
import { Minimize2, Maximize2, Send, MessageCircle, RefreshCw, Play, Square } from 'lucide-react';
import { AvatarRenderer } from './avatar-renderer';
import { useAvatarStore } from '@/lib/store/avatar';
import { useStageStore } from '@/lib/store';
import { useUserProfileStore } from '@/lib/store/user-profile';
import type { SpeechAction } from '@/lib/types/action';
import { toast } from 'sonner';
import './avatar.css';

interface AvatarWidgetProps {
  currentSlideNo?: number;
  size?: number;
}

const CUSTOM_AVATAR_KEY = 'avatar_custom_image';
const MAX_AVATAR_DATA_URL_CHARS = 300_000;

/**
 * Digital Human Avatar Widget.
 * Always renders (idle SVG if service is offline), connects to avatar_service when available.
 * Click avatar to interact: greet, ask questions, or trigger explanations.
 */
export function AvatarWidget({ currentSlideNo, size = 200 }: AvatarWidgetProps) {
  const {
    serviceAvailable,
    avatarVisualState,
    subtitle,
    audioUrl,
    isSpeaking,
    hasError,
    checkHealth,
    loadSession,
    triggerPPTExplain,
    triggerBroadcast,
    triggerProjectIntro,
    sessionId,
  } = useAvatarStore();
  const stage = useStageStore((s) => s.stage);
  const scenes = useStageStore((s) => s.scenes);
  const userAvatar = useUserProfileStore((s) => s.avatar);
  const avatarVoiceEnabled = useUserProfileStore((s) => s.avatarVoiceEnabled);
  const setAvatarVoiceEnabled = useUserProfileStore((s) => s.setAvatarVoiceEnabled);
  const effectiveVoiceEnabled = avatarVoiceEnabled;

  const [collapsed, setCollapsed] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Check avatar service health on mount
  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  // Trigger slide explanation when slide changes (only if service is live)
  useEffect(() => {
    if (serviceAvailable && sessionId && currentSlideNo && currentSlideNo > 0) {
      triggerPPTExplain(sessionId, currentSlideNo);
    }
  }, [serviceAvailable, sessionId, currentSlideNo, triggerPPTExplain]);

  // Initialize avatar session from current stage data once service is reachable.
  useEffect(() => {
    if (!serviceAvailable || !stage?.id || scenes.length === 0) return;
    const targetSessionId = `stage-${stage.id}`;
    if (sessionId === targetSessionId) return;

    const orderedScenes = [...scenes].sort((a, b) => a.order - b.order);
    const pptScripts = orderedScenes
      .map((scene, index) => {
        const speech = scene.actions?.find(
          (action): action is SpeechAction => action.type === 'speech',
        );
        const notes = speech?.text?.trim() || '';
        return {
          slide_no: scene.order > 0 ? scene.order : index + 1,
          title: scene.title,
          bullets: [],
          ...(notes ? { speaker_notes: notes, summary: notes.slice(0, 140) } : {}),
        };
      })
      .filter((item) => item.slide_no > 0);

    if (pptScripts.length === 0) return;

    const introSummary =
      stage.description?.trim() ||
      (pptScripts[0].summary?.trim() || '') ||
      `围绕${stage.name || '当前课堂'}展开讲解。`;

    let avatarImageUrl = '';
    let avatarSource = '';
    if (typeof window !== 'undefined') {
      try {
        const customAvatar = localStorage.getItem(CUSTOM_AVATAR_KEY) || '';
        const preferred = customAvatar.trim() || (userAvatar || '').trim();
        avatarSource = preferred;
        if (preferred.startsWith('data:image/')) {
          if (preferred.length <= MAX_AVATAR_DATA_URL_CHARS) {
            avatarImageUrl = preferred;
          }
        } else if (/^https?:\/\//i.test(preferred)) {
          avatarImageUrl = preferred;
        } else if (preferred.startsWith('/')) {
          avatarImageUrl = `${window.location.origin}${preferred}`;
        }
      } catch {
        // ignore localStorage errors
      }
    }

    const metadata: Record<string, string> = {};
    if (avatarImageUrl) metadata.avatar_image_url = avatarImageUrl;
    if (avatarSource && !avatarSource.startsWith('data:')) metadata.avatar_source = avatarSource;
    if (stage.name?.trim()) metadata.avatar_persona_hint = `课堂主题：${stage.name.trim()}`;

    loadSession(targetSessionId, {
      project_intro: {
        title: stage.name || '课堂讲解',
        summary: introSummary,
        highlights: [],
      },
      ppt_scripts: pptScripts,
      result_events: { events: [] },
      metadata,
    });
  }, [
    serviceAvailable,
    stage?.id,
    stage?.name,
    stage?.description,
    scenes,
    sessionId,
    loadSession,
    userAvatar,
  ]);

  // Focus input when chat opens
  useEffect(() => {
    if (chatOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [chatOpen]);

  const handleAvatarClick = () => {
    if (serviceAvailable && sessionId) {
      // If service is live, toggle chat panel
      setChatOpen(!chatOpen);
    } else if (serviceAvailable) {
      // Session is still initializing; ignore click.
      return;
    } else if (!serviceAvailable) {
      // Try reconnecting
      checkHealth();
    }
  };

  const handleSend = async () => {
    if (!chatInput.trim() || !sessionId || sending) return;
    setSending(true);
    try {
      await triggerBroadcast(sessionId, chatInput.trim());
      setChatInput('');
    } finally {
      setSending(false);
    }
  };

  const handleGreet = async () => {
    if (!sessionId) return;
    await triggerProjectIntro(sessionId);
  };

  const handleExplainSlide = async () => {
    if (!sessionId || !currentSlideNo) return;
    await triggerPPTExplain(sessionId, currentSlideNo);
  };

  const handleToggleAvatarVoice = () => {
    const next = !avatarVoiceEnabled;
    setAvatarVoiceEnabled(next);
    toast.info(next ? '数字人声音已开启' : '数字人声音已关闭');
  };

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="w-12 h-12 rounded-full bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm shadow-lg border border-gray-200/60 dark:border-gray-700/60 flex items-center justify-center hover:scale-105 active:scale-95 transition-transform"
        title="展开数字人助教"
      >
        <Maximize2 className="w-4 h-4 text-gray-600 dark:text-gray-300" />
      </button>
    );
  }

  // Determine display state: use live state if service is up, otherwise idle
  const displayState = serviceAvailable ? avatarVisualState : 'idle';
  const displaySubtitle = serviceAvailable
    ? sessionId
      ? subtitle
      : '正在初始化数字人会话...'
    : '点击我开始互动 👋';
  const sessionReady = serviceAvailable && !!sessionId;

  return (
    <div className="flex flex-col items-center gap-2">
      {/* Controls */}
      <div className="flex items-center gap-1">
        {sessionReady && (
          <>
            <button
              onClick={() => setChatOpen(!chatOpen)}
              className="w-7 h-7 rounded-full bg-white/80 dark:bg-slate-800/80 backdrop-blur-sm shadow-sm border border-gray-200/40 dark:border-gray-700/40 flex items-center justify-center hover:bg-emerald-50 dark:hover:bg-emerald-900/20 hover:text-emerald-600 transition-colors"
              title="与数字人对话"
            >
              <MessageCircle className="w-3.5 h-3.5 text-gray-500" />
            </button>
            <button
              onClick={handleToggleAvatarVoice}
              className="w-7 h-7 rounded-full bg-white/80 dark:bg-slate-800/80 backdrop-blur-sm shadow-sm border border-gray-200/40 dark:border-gray-700/40 flex items-center justify-center hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
              title={
                avatarVoiceEnabled ? '关闭数字人声音' : '开启数字人声音'
              }
            >
              {avatarVoiceEnabled ? (
                <Square className="w-3.5 h-3.5 text-gray-500" />
              ) : (
                <Play className="w-3.5 h-3.5 text-gray-500" />
              )}
            </button>
          </>
        )}
        <button
          onClick={() => setCollapsed(true)}
          className="w-7 h-7 rounded-full bg-white/80 dark:bg-slate-800/80 backdrop-blur-sm shadow-sm border border-gray-200/40 dark:border-gray-700/40 flex items-center justify-center hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          title="收起"
        >
          <Minimize2 className="w-3.5 h-3.5 text-gray-500" />
        </button>
      </div>

      {/* Avatar — clickable */}
      <button
        onClick={handleAvatarClick}
        className="cursor-pointer hover:scale-[1.03] active:scale-[0.97] transition-transform focus:outline-none rounded-full"
        title={sessionReady ? '点击与数字人助教互动' : serviceAvailable ? '数字人会话初始化中' : '点击重新连接'}
      >
        <AvatarRenderer
          avatarState={displayState}
          subtitle={displaySubtitle}
          audioUrl={serviceAvailable && effectiveVoiceEnabled ? audioUrl : null}
          autoPlay={serviceAvailable && effectiveVoiceEnabled}
          audioEnabled={serviceAvailable && avatarVoiceEnabled}
          audioMuted={!avatarVoiceEnabled}
          audioVolume={1}
          size={size}
          showSubtitle={true}
          isSpeaking={serviceAvailable ? isSpeaking : false}
          hasError={serviceAvailable ? hasError : false}
        />
      </button>

      {/* Quick actions & chat panel */}
      {sessionReady && chatOpen && (
        <div className="w-56 bg-white/95 dark:bg-slate-900/95 backdrop-blur-md rounded-xl shadow-lg border border-gray-200/60 dark:border-gray-700/60 overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-200">
          {/* Quick action buttons */}
          <div className="p-2 flex gap-1.5 border-b border-gray-100 dark:border-gray-800">
            <button
              onClick={handleGreet}
              className="flex-1 px-2 py-1.5 text-[11px] rounded-lg bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-900/30 transition-colors font-medium"
            >
              👋 打招呼
            </button>
            {currentSlideNo && (
              <button
                onClick={handleExplainSlide}
                className="flex-1 px-2 py-1.5 text-[11px] rounded-lg bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors font-medium"
              >
                📖 讲解本页
              </button>
            )}
          </div>
          {/* Chat input */}
          <div className="p-2 flex gap-1.5">
            <input
              ref={inputRef}
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="输入问题..."
              className="flex-1 px-2.5 py-1.5 text-xs border rounded-lg bg-background focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
              disabled={sending}
            />
            <button
              onClick={handleSend}
              disabled={sending || !chatInput.trim()}
              className="w-7 h-7 rounded-lg bg-emerald-500 text-white flex items-center justify-center hover:bg-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
            >
              <Send className="w-3 h-3" />
            </button>
          </div>
        </div>
      )}

      {/* Service status indicator */}
      {!serviceAvailable && (
        <div className="flex flex-col items-center gap-1">
          <button
            onClick={() => checkHealth()}
            className="flex items-center gap-1 text-[10px] text-amber-600 dark:text-amber-400 hover:text-emerald-500 transition-colors"
          >
            <RefreshCw className="w-3 h-3" />
            数字人服务未连接
          </button>
          <span className="text-[9px] text-muted-foreground/40 text-center leading-tight max-w-[160px]">
            请启动数字人服务 (端口 8000)
          </span>
        </div>
      )}
    </div>
  );
}
