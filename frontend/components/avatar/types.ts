import type { CSSProperties, ReactNode } from 'react';

export type BackendAvatarState =
  | 'idle'
  | 'speaking'
  | 'paused'
  | 'awaiting_command'
  | 'completed'
  | 'error';

export type AvatarVisualState = 'idle' | 'greet' | 'explain' | 'notify' | 'paused' | 'error';

export type AvatarState = BackendAvatarState | AvatarVisualState;

export interface SubtitlePanelProps {
  subtitle?: string | null;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}

export interface AvatarRendererProps {
  avatarState?: AvatarState | null;
  subtitle?: string | null;
  size?: number | string;
  showSubtitle?: boolean;
  audioUrl?: string | null;
  autoPlay?: boolean;
  audioEnabled?: boolean;
  audioMuted?: boolean;
  audioVolume?: number;
  isSpeaking?: boolean;
  hasError?: boolean;
  className?: string;
  style?: CSSProperties;
  imageStyle?: CSSProperties;
  subtitleClassName?: string;
  subtitleStyle?: CSSProperties;
}

export interface SpeechTask {
  task_id: string;
  session_id: string;
  audio_url: string | null;
  subtitle: string;
  avatar_state: BackendAvatarState;
  mode: string;
  slide_no: number | null;
  status: 'pending' | 'running' | 'success' | 'failed';
  duration_sec: number;
  error_message: string | null;
}

export interface SessionState {
  session_id: string;
  mode: string;
  avatar_state: BackendAvatarState;
  current_slide: number | null;
  total_slides: number;
}
