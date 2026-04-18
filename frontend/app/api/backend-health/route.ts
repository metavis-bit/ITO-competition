import { apiSuccess } from '@/lib/server/api-response';
import { isBackendEnabled, proxyGet } from '@/lib/server/backend-proxy';

interface BackendHealthResponse {
  status?: string;
  rag?: {
    initialized?: boolean;
    error?: string | null;
  };
}

export async function GET() {
  if (!isBackendEnabled()) {
    return apiSuccess({
      healthy: false,
      backendEnabled: false,
      reason: 'backend_disabled',
    });
  }

  try {
    const health = await proxyGet<BackendHealthResponse>('/v1/health', {
      timeout: 5000,
    });
    const healthy = health.status === 'ok';
    return apiSuccess({
      healthy,
      backendEnabled: true,
      ragInitialized: !!health.rag?.initialized,
      ragError: health.rag?.error ?? null,
    });
  } catch (error) {
    return apiSuccess({
      healthy: false,
      backendEnabled: true,
      reason: error instanceof Error ? error.message : 'backend_unreachable',
    });
  }
}
