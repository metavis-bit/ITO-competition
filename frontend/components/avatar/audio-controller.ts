export interface AudioControllerOptions {
  audioUrl?: string | null;
  autoPlay?: boolean;
}

export type AudioPlaybackListener = (isPlaying: boolean) => void;

export class AudioController {
  private audio: HTMLAudioElement | null = null;
  private listeners = new Set<AudioPlaybackListener>();
  private currentSource: string | null = null;
  private _isPlaying = false;
  private _muted = false;
  private _volume = 1;

  constructor(options: AudioControllerOptions = {}) {
    if (typeof Audio !== 'undefined') {
      this.audio = new Audio();
      this.audio.preload = 'auto';
      this.audio.muted = this._muted;
      this.audio.volume = this._volume;
      this.audio.addEventListener('play', this.handlePlay);
      this.audio.addEventListener('pause', this.handlePause);
      this.audio.addEventListener('ended', this.handleEnded);
      this.audio.addEventListener('error', this.handleError);
    }

    if (options.audioUrl) {
      this.setSource(options.audioUrl, options.autoPlay);
    }
  }

  get isPlaying(): boolean {
    return this._isPlaying;
  }

  get source(): string | null {
    return this.currentSource;
  }

  get element(): HTMLAudioElement | null {
    return this.audio;
  }

  subscribe(listener: AudioPlaybackListener): () => void {
    this.listeners.add(listener);
    listener(this._isPlaying);
    return () => {
      this.listeners.delete(listener);
    };
  }

  setSource(audioUrl?: string | null, autoPlay = false): void {
    if (!this.audio) {
      return;
    }

    if (!audioUrl) {
      this.stop();
      this.currentSource = null;
      this.audio.removeAttribute('src');
      this.audio.load();
      return;
    }

    if (this.currentSource !== audioUrl) {
      this.stop();
      this.currentSource = audioUrl;
      this.audio.src = audioUrl;
      this.audio.load();
    }

    if (autoPlay) {
      void this.play();
    }
  }

  async play(): Promise<void> {
    if (!this.audio || !this.currentSource) {
      return;
    }

    try {
      await this.audio.play();
    } catch {
      this.updatePlaying(false);
    }
  }

  pause(): void {
    if (!this.audio) {
      return;
    }

    this.audio.pause();
    this.updatePlaying(false);
  }

  setMuted(muted: boolean): void {
    this._muted = muted;
    if (!this.audio) return;
    this.audio.muted = muted;
    // For avatar UX, turning off voice should immediately silence current playback.
    if (muted) {
      this.stop();
    }
  }

  setVolume(volume: number): void {
    const next = Number.isFinite(volume) ? Math.min(1, Math.max(0, volume)) : 1;
    this._volume = next;
    if (!this.audio) return;
    this.audio.volume = next;
  }

  stop(): void {
    if (!this.audio) {
      return;
    }

    this.audio.pause();
    this.audio.currentTime = 0;
    this.updatePlaying(false);
  }

  destroy(): void {
    if (!this.audio) {
      return;
    }

    this.stop();
    this.audio.removeEventListener('play', this.handlePlay);
    this.audio.removeEventListener('pause', this.handlePause);
    this.audio.removeEventListener('ended', this.handleEnded);
    this.audio.removeEventListener('error', this.handleError);
    this.audio = null;
    this.listeners.clear();
  }

  private readonly handlePlay = () => {
    this.updatePlaying(true);
  };

  private readonly handlePause = () => {
    this.updatePlaying(false);
  };

  private readonly handleEnded = () => {
    this.updatePlaying(false);
  };

  private readonly handleError = () => {
    this.updatePlaying(false);
  };

  private updatePlaying(nextValue: boolean): void {
    if (this._isPlaying === nextValue) {
      return;
    }

    this._isPlaying = nextValue;
    for (const listener of this.listeners) {
      listener(this._isPlaying);
    }
  }
}
