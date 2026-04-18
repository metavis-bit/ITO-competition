/**
 * Version Management API — proxy to FastAPI backend
 *
 * GET  /api/versions?sessionId=xxx  → list version history
 * POST /api/versions               → rollback to a specific version
 */

import { NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  isBackendEnabled,
  proxyGet,
  proxyJsonPost,
  type BackendGenerateResponse,
} from '@/lib/server/backend-proxy';
import type { BackendRollbackRequest } from '@/lib/types/backend';
import { createLogger } from '@/lib/logger';

const log = createLogger('Versions API');

export async function GET(req: NextRequest) {
  if (!isBackendEnabled()) {
    return apiError('INTERNAL_ERROR', 501, 'Backend not enabled');
  }

  const sessionId = req.nextUrl.searchParams.get('sessionId');
  if (!sessionId) {
    return apiError('MISSING_REQUIRED_FIELD', 400, 'sessionId query parameter is required');
  }

  try {
    const result = await proxyGet<{ session_id: string; versions: unknown[] }>(
      `/v1/courseware/versions/${encodeURIComponent(sessionId)}`,
      { signal: req.signal },
    );
    return apiSuccess(result as Record<string, unknown>);
  } catch (err) {
    log.error('Version list error:', err);
    return apiError('UPSTREAM_ERROR', 500, err instanceof Error ? err.message : 'Backend error');
  }
}

export async function POST(req: NextRequest) {
  if (!isBackendEnabled()) {
    return apiError('INTERNAL_ERROR', 501, 'Backend not enabled');
  }

  try {
    const body: BackendRollbackRequest = await req.json();

    if (!body.session_id || !body.version_id) {
      return apiError(
        'MISSING_REQUIRED_FIELD',
        400,
        'session_id and version_id are required',
      );
    }

    const result = await proxyJsonPost<BackendGenerateResponse>('/v1/courseware/rollback', body, {
      signal: req.signal,
      timeout: 60_000,
    });

    return apiSuccess({
      sessionId: result.session_id,
      versionId: result.version_id,
      artifacts: Array.isArray(result.artifacts) ? result.artifacts : [],
      plan: result.plan,
      errors: Array.isArray(result.errors) ? result.errors : [],
      requestedOutputTypes: [],
      missingArtifacts: {
        required: [],
        optional: [],
      },
    });
  } catch (err) {
    log.error('Rollback error:', err);
    return apiError('UPSTREAM_ERROR', 500, err instanceof Error ? err.message : 'Rollback failed');
  }
}
