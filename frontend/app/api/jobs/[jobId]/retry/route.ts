import { NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { isBackendEnabled, proxyJsonPost } from '@/lib/server/backend-proxy';

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ jobId: string }> },
) {
  if (!isBackendEnabled()) {
    return apiError('INTERNAL_ERROR', 501, 'Backend not enabled');
  }

  try {
    const { jobId } = await context.params;
    const result = await proxyJsonPost(`/v1/jobs/${encodeURIComponent(jobId)}/retry`, {}, {
      signal: req.signal,
      timeout: 15_000,
    });
    return apiSuccess(result as Record<string, unknown>);
  } catch (err) {
    return apiError('UPSTREAM_ERROR', 500, err instanceof Error ? err.message : 'Retry failed');
  }
}
