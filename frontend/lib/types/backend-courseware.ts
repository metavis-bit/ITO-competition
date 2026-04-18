import type { OutputArtifactType } from './output-types';

export interface BackendPlanSlide {
  slide_number: number;
  title: string;
  bullet_points: string[];
  notes: string;
  layout: string;
  visual_suggestion: string;
  image_path?: string | null;
}

export interface BackendPlanData {
  slide_count: number;
  game_count: number;
  intent: string;
  slides: BackendPlanSlide[];
  lesson_plan_sections: Array<Record<string, unknown>>;
  game_specs: Array<Record<string, unknown>>;
  animation_steps: Array<Record<string, unknown>>;
}

export interface BackendArtifact {
  artifact_id: string;
  type: string;
  file_path: string;
  metadata: Record<string, unknown>;
  generation_time_sec: number;
  error: string | null;
}

export interface BackendMissingArtifacts {
  required: OutputArtifactType[];
  optional: OutputArtifactType[];
}

export interface BackendCoursewareContent {
  sessionId: string;
  versionId: string | null;
  artifacts: BackendArtifact[];
  plan?: BackendPlanData;
  errors: string[];
  requestedOutputTypes: OutputArtifactType[];
  missingArtifacts: BackendMissingArtifacts;
}
