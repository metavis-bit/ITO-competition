import { NextRequest, NextResponse } from 'next/server';

const AVATAR_URL = process.env.AVATAR_SERVICE_URL || 'http://127.0.0.1:8000';
const AVATAR_ENABLED = process.env.AVATAR_SERVICE_ENABLED === 'true';

function buildUpstreamUrl(baseUrl: string, segments: string[]): string {
  const path = segments.join('/');
  const base = baseUrl.replace(/\/$/, '');
  // Media requests: /api/avatar/media/... → AVATAR_URL/media/...
  if (path.startsWith('media/')) {
    return `${base}/${path}`;
  }
  // Health check: /api/avatar/health → AVATAR_URL/health
  if (path === 'health') {
    return `${base}/health`;
  }
  // API requests: /api/avatar/... → AVATAR_URL/api/avatar/...
  return `${base}/api/avatar/${path}`;
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  if (!AVATAR_ENABLED) {
    return NextResponse.json({ error: 'Avatar service is not enabled' }, { status: 503 });
  }

  const { path } = await params;
  const baseUrl = AVATAR_URL;
  const url = buildUpstreamUrl(baseUrl, path);

  try {
    const body = await request.json();
    const runtimeVlmApiKey = request.headers.get('x-avatar-vlm-api-key')?.trim();
    const runtimeVlmBaseUrl = request.headers.get('x-avatar-vlm-base-url')?.trim();
    const runtimeVlmModel = request.headers.get('x-avatar-vlm-model')?.trim();
    const runtimeVlmProvider = request.headers.get('x-avatar-vlm-provider')?.trim();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (runtimeVlmApiKey) headers['x-avatar-vlm-api-key'] = runtimeVlmApiKey;
    if (runtimeVlmBaseUrl) headers['x-avatar-vlm-base-url'] = runtimeVlmBaseUrl;
    if (runtimeVlmModel) headers['x-avatar-vlm-model'] = runtimeVlmModel;
    if (runtimeVlmProvider) headers['x-avatar-vlm-provider'] = runtimeVlmProvider;

    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      const errorText = await resp.text().catch(() => 'Unknown error');
      return NextResponse.json({ error: errorText }, { status: resp.status });
    }

    const data = await resp.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Avatar service unreachable';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  if (!AVATAR_ENABLED) {
    return NextResponse.json({ error: 'Avatar service is not enabled' }, { status: 503 });
  }

  const { path } = await params;
  const baseUrl = AVATAR_URL;
  const url = buildUpstreamUrl(baseUrl, path);

  try {
    const runtimeVlmApiKey = request.headers.get('x-avatar-vlm-api-key')?.trim();
    const runtimeVlmBaseUrl = request.headers.get('x-avatar-vlm-base-url')?.trim();
    const runtimeVlmModel = request.headers.get('x-avatar-vlm-model')?.trim();
    const runtimeVlmProvider = request.headers.get('x-avatar-vlm-provider')?.trim();
    const headers: Record<string, string> = {};
    if (runtimeVlmApiKey) headers['x-avatar-vlm-api-key'] = runtimeVlmApiKey;
    if (runtimeVlmBaseUrl) headers['x-avatar-vlm-base-url'] = runtimeVlmBaseUrl;
    if (runtimeVlmModel) headers['x-avatar-vlm-model'] = runtimeVlmModel;
    if (runtimeVlmProvider) headers['x-avatar-vlm-provider'] = runtimeVlmProvider;

    const resp = await fetch(url, { headers });

    if (!resp.ok) {
      const errorText = await resp.text().catch(() => 'Unknown error');
      return NextResponse.json({ error: errorText }, { status: resp.status });
    }

    // Binary content (audio files)
    const contentType = resp.headers.get('content-type') || '';
    if (
      contentType.includes('audio/') ||
      contentType.includes('application/octet-stream') ||
      path.join('/').startsWith('media/')
    ) {
      const buffer = await resp.arrayBuffer();
      return new NextResponse(buffer, {
        status: 200,
        headers: {
          'Content-Type': contentType || 'audio/mpeg',
          'Cache-Control': 'public, max-age=3600',
        },
      });
    }

    const data = await resp.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Avatar service unreachable';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
