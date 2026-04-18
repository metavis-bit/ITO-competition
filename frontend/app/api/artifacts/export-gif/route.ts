import { NextRequest, NextResponse } from 'next/server';
import { isBackendEnabled, getBackendUrl } from '@/lib/server/backend-proxy';

export async function GET(request: NextRequest) {
  if (!isBackendEnabled()) {
    return NextResponse.json({ error: 'Backend not enabled' }, { status: 503 });
  }

  const { searchParams } = new URL(request.url);
  const sessionId = searchParams.get('session_id') || searchParams.get('sessionId');
  const versionId = searchParams.get('version_id') || searchParams.get('versionId');

  if (!sessionId) {
    return NextResponse.json({ error: 'Missing session_id' }, { status: 400 });
  }

  try {
    const url = getBackendUrl(
      `/v1/artifacts/export-gif?session_id=${encodeURIComponent(sessionId)}${
        versionId ? `&version_id=${encodeURIComponent(versionId)}` : ''
      }`,
    );
    const resp = await fetch(url);

    if (!resp.ok) {
      const errorText = await resp.text().catch(() => 'Unknown error');
      return NextResponse.json({ error: errorText }, { status: resp.status });
    }

    const buffer = await resp.arrayBuffer();
    return new NextResponse(buffer, {
      status: 200,
      headers: {
        'Content-Type': 'image/gif',
        'Content-Disposition': `attachment; filename="animation-${sessionId}${versionId ? `-${versionId}` : ''}.gif"`,
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
