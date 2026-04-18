import { NextRequest, NextResponse } from 'next/server';
import { isBackendEnabled, getBackendUrl } from '@/lib/server/backend-proxy';
import { createLogger } from '@/lib/logger';

const log = createLogger('Reference Upload');

/**
 * Upload reference file to backend's /v1/knowledge/upload.
 *
 * Streams the original multipart body directly to backend
 * to avoid Node.js FormData re-serialization issues.
 */
export async function POST(req: NextRequest) {
  if (!isBackendEnabled()) {
    return NextResponse.json({ error: 'Backend not enabled' }, { status: 503 });
  }

  try {
    const contentType = req.headers.get('content-type') || '';
    if (!contentType.includes('multipart/form-data')) {
      return NextResponse.json({ error: 'Expected multipart/form-data' }, { status: 400 });
    }

    const url = getBackendUrl('/v1/knowledge/upload');

    // Stream the original request body directly to backend
    // This preserves the multipart boundary and avoids re-serialization
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': contentType },
      body: req.body,
      signal: req.signal,
      // @ts-expect-error -- Node.js fetch supports duplex for streaming
      duplex: 'half',
    });

    if (!resp.ok) {
      const errorText = await resp.text().catch(() => 'Unknown error');
      log.error('Backend upload error:', resp.status, errorText);
      return NextResponse.json(
        { error: `Backend error: ${errorText}` },
        { status: resp.status },
      );
    }

    const data = await resp.json();
    return NextResponse.json(data);
  } catch (err) {
    log.error('Reference upload failed:', err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : 'Upload failed' },
      { status: 502 },
    );
  }
}

