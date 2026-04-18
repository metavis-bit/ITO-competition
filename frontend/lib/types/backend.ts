/**
 * TypeScript type definitions for the ITO FastAPI backend API.
 *
 * These types mirror the Pydantic models defined in:
 *   - src/rag/api/server.py (request/response models)
 *   - src/rag/domain/models.py (domain models)
 *   - src/rag/dialogue/dialogue_manager.py (dialogue state)
 *
 * @see INTEGRATION_MASTER_PLAN.md — Stage C.1 Data Model Mapping
 */

// ── Teaching Intent ─────────────────────────────────────────────

export interface BackendTeachingIntent {
  topic: string;
  subject?: string;
  target_audience?: string;
  teaching_goal?: string;
  grade_level?: string;
  page_range?: string;
  key_focus?: string[];
  difficulties?: string[];
  game_types?: string[];
  special_requirements?: string;
  reference_files?: Record<string, unknown>[];
}

// ── Courseware Generate ─────────────────────────────────────────

export interface BackendGenerateRequest {
  session_id?: string;
  topic: string;
  subject?: string;
  target_audience?: string;
  teaching_goal?: string;
  grade_level?: string;
  page_range?: string;
  key_focus?: string[];
  difficulties?: string[];
  game_types?: string[];
  special_requirements?: string;
  indexes?: string[];
  output_types?: string[];
}

export interface BackendArtifact {
  artifact_id: string;
  type: string;
  file_path: string;
  metadata: Record<string, unknown>;
  generation_time_sec: number;
  error: string | null;
}

export interface BackendGenerateResponse {
  session_id: string;
  version_id: string | null;
  artifacts: BackendArtifact[];
  errors: string[];
  total_time_sec: number;
  plan?: {
    slide_count: number;
    game_count: number;
    intent: string;
  };
}

// ── Outline Stream ──────────────────────────────────────────────

export interface BackendStreamRequest {
  session_id?: string;
  topic: string;
  target_audience?: string;
  teaching_goal?: string;
  page_range?: string;
  key_focus?: string[];
  indexes?: string[];
}

// ── Chat (Multi-turn Dialogue) ──────────────────────────────────

export interface BackendChatRequest {
  session_id?: string;
  message: string;
  session_type?: 'requirements' | 'qa' | 'discussion';
  discussion_topic?: string;
  discussion_prompt?: string;
  trigger_agent_id?: string;
  messages?: Array<Record<string, unknown>>;
  agent_ids?: string[];
  agent_configs?: Array<Record<string, unknown>>;
  user_profile?: Record<string, unknown>;
}

export interface BackendChatReplyData {
  session_id: string;
  message: string;
  state: 'greeting' | 'collecting' | 'confirming' | 'ready' | 'generating' | 'iterating';
  collected_info: string;
  is_complete: boolean;
  missing_fields: string[];
}

export interface BackendIntentCollectedData {
  session_id: string;
  intent: BackendTeachingIntent;
}

export interface BackendAgentReplyData {
  session_id: string;
  agent_id: string;
  agent_name: string;
  agent_role: string;
  agent_avatar?: string;
  agent_color?: string;
  provider_id?: string;
  provider_name?: string;
  model?: string;
  message: string;
}

export interface BackendCueUserData {
  session_id: string;
  from_agent_id?: string;
  prompt?: string;
}

// ── Refine ──────────────────────────────────────────────────────

export interface BackendRefineRequest {
  session_id: string;
  feedback: string;
  cascade_level?: number;
  target_types?: string[];
}

// ── Knowledge / Ingest ──────────────────────────────────────────

export interface BackendIngestRequest {
  dir_path: string;
  index?: string;
  session_id?: string;
}

export interface BackendQueryRequest {
  question: string;
  indexes?: string[];
  top_k?: number;
}

// ── Version Management ──────────────────────────────────────────

export interface BackendVersionInfo {
  version_id: string;
  session_id: string;
  created_at: string;
  plan_summary?: string;
}

export interface BackendRollbackRequest {
  session_id: string;
  version_id: string;
}

export type BackendJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface BackendJobArtifactStatus {
  type: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  error: string | null;
}

export interface BackendCoursewareJob {
  job_id: string;
  status: BackendJobStatus;
  stage: string;
  progress: number;
  error: string | null;
  session_id: string;
  version_id: string | null;
  cancel_requested: boolean;
  created_at: number;
  updated_at: number;
  started_at: number | null;
  finished_at: number | null;
  artifact_statuses: BackendJobArtifactStatus[];
  result?: BackendGenerateResponse;
}

// ── SSE Event Envelope ──────────────────────────────────────────

export interface BackendSSEEvent {
  event: string;
  data: Record<string, unknown>;
}

/** Discriminated union for chat SSE events */
export type BackendChatSSEEvent =
  | { event: 'CHAT_REPLY'; data: BackendChatReplyData }
  | { event: 'INTENT_COLLECTED'; data: BackendIntentCollectedData }
  | { event: 'AGENT_REPLY'; data: BackendAgentReplyData }
  | { event: 'CUE_USER'; data: BackendCueUserData };

/** Discriminated union for outline SSE events */
export type BackendOutlineSSEEvent =
  | { event: 'OUTLINE_CHUNK'; data: Record<string, unknown> }
  | { event: 'OUTLINE_DONE'; data: { plan: Record<string, unknown> } }
  | { event: 'PIPELINE_DONE'; data: Record<string, unknown> }
  | { event: 'error'; data: { error: string } };

// ── Data Model Mapping Helpers (C.1) ────────────────────────────

import type { SceneOutline } from '@/lib/types/generation';

/**
 * Convert a backend CoursewarePlan slide into a frontend SceneOutline.
 * Used by the proxy layer when translating backend responses.
 */
export function backendSlideToOutline(
  slide: {
    title?: string;
    notes?: string;
    bullet_points?: string[];
    layout?: string;
  },
  index: number,
  language: 'zh-CN' | 'en-US' = 'zh-CN',
): Partial<SceneOutline> {
  return {
    type: slide.layout === 'interactive' ? 'interactive' : 'slide',
    title: slide.title || '',
    description: slide.notes || '',
    order: index + 1,
    language,
  };
}

/**
 * Convert frontend UserRequirements into a backend TeachingIntent.
 */
export function requirementsToIntent(requirement: string): BackendTeachingIntent {
  return {
    topic: requirement,
    target_audience: '',
    teaching_goal: '',
    page_range: '10-15',
    key_focus: [],
  };
}
