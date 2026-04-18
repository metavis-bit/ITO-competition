import { NextRequest, NextResponse } from 'next/server';
import { isBackendEnabled, getBackendUrl } from '@/lib/server/backend-proxy';

export async function POST(request: NextRequest) {
  if (!isBackendEnabled()) {
    return NextResponse.json({ error: 'Backend not enabled' }, { status: 503 });
  }

  try {
    const contentType = request.headers.get('content-type') || '';
    const url = getBackendUrl('/v1/video/process');

    // Stream original multipart body directly to avoid re-serialization issues
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': contentType },
      body: request.body,
      signal: request.signal,
      // @ts-expect-error -- Node.js fetch supports duplex for streaming
      duplex: 'half',
    });

    if (!resp.ok) {
      const errorText = await resp.text().catch(() => 'Unknown error');
      return NextResponse.json({ error: errorText }, { status: resp.status });
    }

    const data = await resp.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
