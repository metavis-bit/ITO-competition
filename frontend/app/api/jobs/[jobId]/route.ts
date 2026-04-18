import { NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { isBackendEnabled, proxyGet } from '@/lib/server/backend-proxy';
import type { BackendCoursewareJob } from '@/lib/types/backend';
import type { BackendGenerateResponse } from '@/lib/server/backend-proxy';
import { normalizeOutputTypes } from '@/lib/types/output-types';

function collectArtifactTypes(
  artifacts: Array<{ type?: string }> | undefined,
): Set<string> {
  const types = new Set<string>();
  for (const artifact of artifacts || []) {
    const type = (artifact?.type || '').trim();
    if (type) {
      types.add(type);
    }
  }
  return types;
}

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ jobId: string }> },
) {
  if (!isBackendEnabled()) {
    return apiError('INTERNAL_ERROR', 501, 'Backend not enabled');
  }

  try {
    const { jobId } = await context.params;
    const result = await proxyGet<BackendCoursewareJob>(`/v1/jobs/${encodeURIComponent(jobId)}`, {
      signal: req.signal,
      timeout: 30_000,
    });

    const response: Record<string, unknown> = {
      jobId: result.job_id,
      status: result.status,
      stage: result.stage,
      progress: result.progress,
      error: result.error,
      sessionId: result.session_id,
      versionId: result.version_id,
      cancelRequested: result.cancel_requested,
      artifactStatuses: result.artifact_statuses,
      createdAt: result.created_at,
      updatedAt: result.updated_at,
      startedAt: result.started_at,
      finishedAt: result.finished_at,
    };

    const serializedResult = result.result as BackendGenerateResponse | undefined;
    if (serializedResult) {
      const artifacts = Array.isArray(serializedResult.artifacts) ? serializedResult.artifacts : [];
      const requestedOutputTypes = normalizeOutputTypes(
        result.artifact_statuses?.map((item) => item.type) || [],
      );
      const artifactTypes = collectArtifactTypes(artifacts);
      response.content = {
        sessionId: serializedResult.session_id,
        versionId: serializedResult.version_id,
        artifacts,
        plan: serializedResult.plan,
        errors: Array.isArray(serializedResult.errors) ? serializedResult.errors : [],
        requestedOutputTypes,
        missingArtifacts: {
          required: [],
          optional: requestedOutputTypes.filter((type) => !artifactTypes.has(type)),
        },
      };
    }

    return apiSuccess(response);
  } catch (err) {
    return apiError('UPSTREAM_ERROR', 500, err instanceof Error ? err.message : 'Job fetch failed');
  }
}
