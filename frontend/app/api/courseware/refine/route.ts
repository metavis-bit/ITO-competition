import { NextRequest, NextResponse } from 'next/server';
import {
  isBackendEnabled,
  proxyJsonPost,
  type BackendGenerateResponse,
} from '@/lib/server/backend-proxy';

export async function POST(request: NextRequest) {
  if (!isBackendEnabled()) {
    return NextResponse.json({ error: 'Backend not enabled' }, { status: 503 });
  }

  try {
    const body = await request.json();
    const data = await proxyJsonPost<BackendGenerateResponse>('/v1/courseware/refine', body, {
      timeout: 300_000,
    });
    return NextResponse.json({
      sessionId: data.session_id,
      versionId: data.version_id,
      artifacts: Array.isArray(data.artifacts) ? data.artifacts : [],
      plan: data.plan,
      errors: Array.isArray(data.errors) ? data.errors : [],
      requestedOutputTypes: [],
      missingArtifacts: {
        required: [],
        optional: [],
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
