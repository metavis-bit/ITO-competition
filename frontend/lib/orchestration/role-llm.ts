import type { ProviderId } from '@/lib/types/provider';

type ModelLike = { id: string; name?: string };

type ProviderConfigLike = {
  apiKey?: string;
  baseUrl?: string;
  serverBaseUrl?: string;
  defaultBaseUrl?: string;
  isServerConfigured?: boolean;
  name?: string;
  models?: ModelLike[];
};

interface ResolveInput {
  role: string;
  providerId: ProviderId;
  modelId: string;
  providersConfig: Partial<Record<ProviderId, ProviderConfigLike>>;
  preferredProviderId?: ProviderId;
  preferredModelId?: string;
}

export interface ResolvedRoleLLMConfig {
  providerId: ProviderId;
  providerName: string;
  modelId: string;
  apiKey: string;
  baseUrl: string;
}

const ROLE_PROVIDER_PRIORITY: Record<string, ProviderId[]> = {
  teacher: ['openai', 'qwen', 'glm'],
  assistant: ['qwen', 'glm', 'openai'],
  student: ['deepseek', 'kimi', 'openai'],
};

const ROLE_MODEL_DEFAULT: Partial<Record<ProviderId, string>> = {
  openai: 'gpt-4o-mini',
  qwen: 'qwen3.5-plus',
  deepseek: 'deepseek-chat',
  glm: 'glm-4.7-flash',
  kimi: 'kimi-k2.5',
  doubao: 'doubao-seed-2-0-lite-260215',
  siliconflow: 'deepseek-ai/DeepSeek-V3',
  grok: 'grok-4-fast-non-reasoning',
};

function hasProviderCredential(cfg: ProviderConfigLike | undefined): boolean {
  if (!cfg) return false;
  return Boolean((cfg.apiKey || '').trim()) || Boolean(cfg.isServerConfigured);
}

function pickProviderId(input: ResolveInput): ProviderId {
  if (input.preferredProviderId && input.providersConfig[input.preferredProviderId]) {
    return input.preferredProviderId;
  }
  const role = (input.role || '').toLowerCase();
  const preferred = ROLE_PROVIDER_PRIORITY[role] || ['openai'];
  const configured = preferred.find((pid) => hasProviderCredential(input.providersConfig[pid]));
  if (configured) return configured;
  if (input.providersConfig[input.providerId]) return input.providerId;
  return preferred[0];
}

function pickModelId(providerId: ProviderId, input: ResolveInput): string {
  const cfg = input.providersConfig[providerId];
  const preferredModelId = (input.preferredModelId || '').trim();
  if (
    preferredModelId &&
    ((cfg?.models?.some((m) => m.id === preferredModelId) ?? false) ||
      providerId === input.preferredProviderId)
  ) {
    return preferredModelId;
  }
  const preferred = ROLE_MODEL_DEFAULT[providerId];
  if (preferred && cfg?.models?.some((m) => m.id === preferred)) {
    return preferred;
  }
  if (cfg?.models?.length) {
    return cfg.models[0].id;
  }
  if (providerId === input.providerId && input.modelId) {
    return input.modelId;
  }
  return preferred || input.modelId || 'gpt-4o-mini';
}

export function resolveRoleLLMConfig(input: ResolveInput): ResolvedRoleLLMConfig {
  const providerId = pickProviderId(input);
  const cfg = input.providersConfig[providerId];
  const modelId = pickModelId(providerId, input);
  return {
    providerId,
    providerName: cfg?.name || providerId,
    modelId,
    apiKey: (cfg?.apiKey || '').trim(),
    baseUrl: (cfg?.serverBaseUrl || cfg?.baseUrl || cfg?.defaultBaseUrl || '').trim(),
  };
}
