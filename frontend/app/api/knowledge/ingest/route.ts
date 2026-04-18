import { NextRequest, NextResponse } from 'next/server';
import { isBackendEnabled, proxyJsonPost } from '@/lib/server/backend-proxy';

export async function POST(request: NextRequest) {
  if (!isBackendEnabled()) {
    return NextResponse.json({ error: 'Backend not enabled' }, { status: 503 });
  }

  try {
    const body = await request.json();
    const data = await proxyJsonPost('/v1/knowledge/ingest', body, { timeout: 300_000 });
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
