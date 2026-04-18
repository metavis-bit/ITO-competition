'use client';

import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';

import { AudioController } from './audio-controller';
import { AvatarStateMachine } from './avatar-state-machine';
import { SubtitlePanel } from './subtitle-panel';
import type { AvatarRendererProps, AvatarVisualState } from './types';

/** Default SVG assets per visual state */
const defaultAssetMap: Record<AvatarVisualState, string> = {
  idle: '/avatar/avatar_idle.jpg',
  greet: '/avatar/avatar_greet.jpg',
  explain: '/avatar/avatar_explain.jpg',
  notify: '/avatar/avatar_notify.jpg',
  paused: '/avatar/avatar_paused.jpg',
  error: '/avatar/avatar_error.png',
};

const CUSTOM_AVATAR_KEY = 'avatar_custom_image';

/** Read custom avatar from localStorage (data URL or path) */
function getCustomAvatar(): string | null {
  try {
    return localStorage.getItem(CUSTOM_AVATAR_KEY);
  } catch {
    return null;
  }
}

/** Save custom avatar to localStorage */
export function setCustomAvatar(dataUrl: string | null) {
  try {
    if (dataUrl) {
      localStorage.setItem(CUSTOM_AVATAR_KEY, dataUrl);
    } else {
      localStorage.removeItem(CUSTOM_AVATAR_KEY);
    }
    // Dispatch event so all AvatarRenderer instances react
    window.dispatchEvent(new CustomEvent('avatar-custom-changed'));
  } catch { /* ignore */ }
}

function resolveAssetMap(customSrc: string | null): Record<AvatarVisualState, string> {
  if (customSrc) {
    // All states use the same custom image; CSS animations handle state differentiation
    return {
      idle: customSrc,
      greet: customSrc,
      explain: customSrc,
      notify: customSrc,
      paused: customSrc,
      error: customSrc,
    };
  }
  return defaultAssetMap;
}

const imageStyleBase: CSSProperties = {
  display: 'block',
  width: '100%',
  height: '100%',
  objectFit: 'contain',
  userSelect: 'none',
  pointerEvents: 'none',
};

function resolveSize(size?: number | string): CSSProperties {
  if (typeof size === 'number') {
    return { width: size, height: size };
  }
  if (typeof size === 'string' && size.trim()) {
    return { width: size, height: size };
  }
  return { width: 320, height: 320 };
}

export function AvatarRenderer({
  avatarState = 'idle',
  subtitle,
  size = 320,
  showSubtitle = true,
  audioUrl,
  autoPlay = false,
  audioEnabled = true,
  audioMuted = false,
  audioVolume = 1,
  isSpeaking = false,
  hasError = false,
  className,
  style,
  imageStyle,
  subtitleClassName,
  subtitleStyle,
}: AvatarRendererProps) {
  const [audioController] = useState(() => new AudioController());
  const [controllerPlaying, setControllerPlaying] = useState(false);
  const [stateMachine] = useState(() => new AvatarStateMachine());
  const [customAvatar, setCustomAvatarState] = useState<string | null>(() => getCustomAvatar());
  const [failedPreferredSrc, setFailedPreferredSrc] = useState<string | null>(null);

  // Load custom avatar on mount and listen for changes
  useEffect(() => {
    const handler = () => setCustomAvatarState(getCustomAvatar());
    window.addEventListener('avatar-custom-changed', handler);
    return () => window.removeEventListener('avatar-custom-changed', handler);
  }, []);

  useEffect(() => {
    const unsubscribe = audioController.subscribe(setControllerPlaying);
    return () => {
      unsubscribe();
      audioController.destroy();
    };
  }, [audioController]);

  useEffect(() => {
    if (!audioEnabled) {
      audioController.setSource(null, false);
      return;
    }
    audioController.setSource(audioUrl, autoPlay);
  }, [audioController, audioEnabled, audioUrl, autoPlay]);

  useEffect(() => {
    audioController.setMuted(audioMuted);
  }, [audioController, audioMuted]);

  useEffect(() => {
    audioController.setVolume(audioVolume);
  }, [audioController, audioVolume]);

  const assetMap = resolveAssetMap(customAvatar);
  const machineState = stateMachine.update({
    avatarState,
    isSpeaking: isSpeaking || controllerPlaying,
    hasError,
  });
  const visualState = machineState.visualState;
  const defaultSrc = defaultAssetMap[visualState];
  const preferredSrc = assetMap[visualState] || defaultSrc;
  const src = failedPreferredSrc === preferredSrc ? defaultSrc : preferredSrc;
  const sizeStyle = resolveSize(size);
  const rootClassName = [
    'avatar-ui-kit',
    `avatar-ui-kit--${visualState}`,
    machineState.isSpeaking ? 'avatar-ui-kit--speaking' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={rootClassName} style={style} data-avatar-state={visualState}>
      <div className="avatar-ui-kit__frame" style={sizeStyle}>
        <img
          className="avatar-ui-kit__image"
          src={src}
          alt={`avatar-${visualState}`}
          draggable={false}
          style={{ ...imageStyleBase, ...imageStyle }}
          onError={() => {
            if (src !== defaultSrc && failedPreferredSrc !== preferredSrc) {
              setFailedPreferredSrc(preferredSrc);
            }
          }}
        />
      </div>
      {showSubtitle ? (
        <SubtitlePanel
          subtitle={subtitle}
          className={subtitleClassName}
          style={{ maxWidth: typeof size === 'number' ? size : 420, ...subtitleStyle }}
        />
      ) : null}
    </div>
  );
}
