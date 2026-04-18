/**
 * Artifact Download API — proxy file download from FastAPI backend
 *
 * GET /api/artifacts/download?sessionId=xxx&type=pptx
 *
 * Supported types: pptx, docx, game_html, animation_html
 */

import { NextRequest } from 'next/server';
import { apiError } from '@/lib/server/api-response';
import { isBackendEnabled, getBackendUrl } from '@/lib/server/backend-proxy';
import { createLogger } from '@/lib/logger';

const log = createLogger('Artifact Download');

export async function GET(req: NextRequest) {
  if (!isBackendEnabled()) {
    return apiError('INTERNAL_ERROR', 501, 'Backend not enabled');
  }

  const sessionId = req.nextUrl.searchParams.get('sessionId');
  const artifactType = req.nextUrl.searchParams.get('type');
  const versionId = req.nextUrl.searchParams.get('versionId');

  if (!sessionId || !artifactType) {
    return apiError(
      'MISSING_REQUIRED_FIELD',
      400,
      'sessionId and type query parameters are required',
    );
  }

  try {
    const url = getBackendUrl(
      `/v1/artifacts/download?session_id=${encodeURIComponent(sessionId)}&artifact_type=${encodeURIComponent(artifactType)}${
        versionId ? `&version_id=${encodeURIComponent(versionId)}` : ''
      }`,
    );

    const resp = await fetch(url, { signal: req.signal });

    if (!resp.ok) {
      const errText = await resp.text().catch(() => 'Download failed');
      log.error('Backend download error:', errText);
      return apiError('UPSTREAM_ERROR', resp.status, errText);
    }

    // Forward the file response with proper headers
    const headers = new Headers();

    const contentDisposition = resp.headers.get('content-disposition');
    if (contentDisposition) {
      headers.set('content-disposition', contentDisposition);
    } else {
      // Generate a sensible filename
      const ext =
        artifactType === 'game_html' || artifactType === 'animation_html'
          ? 'html'
          : artifactType;
      headers.set('content-disposition', `attachment; filename="courseware.${ext}"`);
    }

    headers.set(
      'content-type',
      resp.headers.get('content-type') || 'application/octet-stream',
    );

    const contentLength = resp.headers.get('content-length');
    if (contentLength) {
      headers.set('content-length', contentLength);
    }

    return new Response(resp.body, { headers });
  } catch (err) {
    log.error('Download proxy error:', err);
    return apiError(
      'UPSTREAM_ERROR',
      500,
      err instanceof Error ? err.message : 'Download failed',
    );
  }
}
