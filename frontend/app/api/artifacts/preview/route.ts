import { NextRequest, NextResponse } from 'next/server';
import { isBackendEnabled, getBackendUrl } from '@/lib/server/backend-proxy';

export async function GET(request: NextRequest) {
  if (!isBackendEnabled()) {
    return NextResponse.json({ error: 'Backend not enabled' }, { status: 503 });
  }

  const { searchParams } = new URL(request.url);
  const sessionId = searchParams.get('session_id') || searchParams.get('sessionId');
  const artifactType = searchParams.get('artifact_type') || searchParams.get('type');
  const versionId = searchParams.get('version_id') || searchParams.get('versionId');

  if (!sessionId || !artifactType) {
    return NextResponse.json({ error: 'Missing session_id or artifact_type' }, { status: 400 });
  }

  try {
    const url = getBackendUrl(
      `/v1/artifacts/preview?session_id=${encodeURIComponent(sessionId)}&artifact_type=${encodeURIComponent(artifactType)}${
        versionId ? `&version_id=${encodeURIComponent(versionId)}` : ''
      }`,
    );
    const resp = await fetch(url);

    if (!resp.ok) {
      const errorText = await resp.text().catch(() => 'Unknown error');
      return NextResponse.json({ error: errorText }, { status: resp.status });
    }

    const html = await resp.text();
    return new NextResponse(html, {
      status: 200,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
