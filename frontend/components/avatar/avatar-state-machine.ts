import type { AvatarState, AvatarVisualState } from './types';

export interface AvatarStateMachineInput {
  avatarState?: AvatarState | null;
  isSpeaking?: boolean;
  hasError?: boolean;
}

export interface AvatarStateMachineResult {
  visualState: AvatarVisualState;
  isSpeaking: boolean;
  hasError: boolean;
}

export function resolveAvatarVisualState({
  avatarState,
  isSpeaking = false,
  hasError = false,
}: AvatarStateMachineInput): AvatarVisualState {
  if (hasError || avatarState === 'error') {
    return 'error';
  }

  if (avatarState === 'paused') {
    return 'paused';
  }

  if (
    avatarState === 'greet' ||
    avatarState === 'explain' ||
    avatarState === 'notify' ||
    avatarState === 'idle'
  ) {
    return avatarState;
  }

  if (avatarState === 'speaking' || isSpeaking) {
    return 'explain';
  }

  return 'idle';
}

export class AvatarStateMachine {
  private currentState: AvatarVisualState = 'idle';

  update(input: AvatarStateMachineInput): AvatarStateMachineResult {
    const nextState = resolveAvatarVisualState(input);
    this.currentState = nextState;
    return {
      visualState: nextState,
      isSpeaking: Boolean(input.isSpeaking),
      hasError: Boolean(input.hasError || input.avatarState === 'error'),
    };
  }

  get state(): AvatarVisualState {
    return this.currentState;
  }

  reset(nextState: AvatarVisualState = 'idle'): AvatarVisualState {
    this.currentState = nextState;
    return this.currentState;
  }
}
