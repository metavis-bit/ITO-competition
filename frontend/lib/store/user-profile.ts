/**
 * User Profile Store
 * Persists avatar, nickname & bio to localStorage
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/** Predefined avatar options */
export const AVATAR_OPTIONS = [
  '/avatars/user.png',
  '/avatars/teacher-2.png',
  '/avatars/assist-2.png',
  '/avatars/clown-2.png',
  '/avatars/curious-2.png',
  '/avatars/note-taker-2.png',
  '/avatars/thinker-2.png',
] as const;

export interface UserProfileState {
  /** Local avatar path or data-URL (for custom uploads) */
  avatar: string;
  nickname: string;
  bio: string;
  /** Subject taught, e.g. "高中生物" */
  subject: string;
  /** Grade level, e.g. "高一" */
  gradeLevel: string;
  /** Teaching style preference, e.g. "互动探究" */
  teachingStyle: string;
  /** Optional avatar service base URL override, e.g. http://127.0.0.1:8000 */
  avatarServiceUrl: string;
  /** Optional avatar service token (for proxy Authorization forwarding) */
  avatarServiceApiKey: string;
  /** Whether avatar multimodal voice-profile uses global language-model settings. */
  avatarVlmUseGlobalModelConfig: boolean;
  /** Optional override API key for avatar multimodal voice-profile. */
  avatarVlmApiKey: string;
  /** Optional override base URL for avatar multimodal voice-profile. */
  avatarVlmBaseUrl: string;
  /** Optional override model id for avatar multimodal voice-profile. */
  avatarVlmModel: string;
  /** Enable digital-human voice output (audio URL + local read aloud button) */
  avatarVoiceEnabled: boolean;
  setAvatar: (avatar: string) => void;
  setNickname: (nickname: string) => void;
  setBio: (bio: string) => void;
  setSubject: (subject: string) => void;
  setGradeLevel: (gradeLevel: string) => void;
  setTeachingStyle: (teachingStyle: string) => void;
  setAvatarServiceUrl: (url: string) => void;
  setAvatarServiceApiKey: (key: string) => void;
  setAvatarVlmUseGlobalModelConfig: (enabled: boolean) => void;
  setAvatarVlmApiKey: (key: string) => void;
  setAvatarVlmBaseUrl: (url: string) => void;
  setAvatarVlmModel: (model: string) => void;
  setAvatarVoiceEnabled: (enabled: boolean) => void;
}

export const useUserProfileStore = create<UserProfileState>()(
  persist(
    (set) => ({
      avatar: AVATAR_OPTIONS[0],
      nickname: '',
      bio: '',
      subject: '生物',
      gradeLevel: '',
      teachingStyle: '',
      avatarServiceUrl: '',
      avatarServiceApiKey: '',
      avatarVlmUseGlobalModelConfig: true,
      avatarVlmApiKey: '',
      avatarVlmBaseUrl: '',
      avatarVlmModel: '',
      avatarVoiceEnabled: true,
      setAvatar: (avatar) => set({ avatar }),
      setNickname: (nickname) => set({ nickname }),
      setBio: (bio) => set({ bio }),
      setSubject: (subject) => set({ subject }),
      setGradeLevel: (gradeLevel) => set({ gradeLevel }),
      setTeachingStyle: (teachingStyle) => set({ teachingStyle }),
      setAvatarServiceUrl: (avatarServiceUrl) => set({ avatarServiceUrl }),
      setAvatarServiceApiKey: (avatarServiceApiKey) => set({ avatarServiceApiKey }),
      setAvatarVlmUseGlobalModelConfig: (avatarVlmUseGlobalModelConfig) =>
        set({ avatarVlmUseGlobalModelConfig }),
      setAvatarVlmApiKey: (avatarVlmApiKey) => set({ avatarVlmApiKey }),
      setAvatarVlmBaseUrl: (avatarVlmBaseUrl) => set({ avatarVlmBaseUrl }),
      setAvatarVlmModel: (avatarVlmModel) => set({ avatarVlmModel }),
      setAvatarVoiceEnabled: (avatarVoiceEnabled) => set({ avatarVoiceEnabled }),
    }),
    {
      name: 'user-profile-storage',
    },
  ),
);

