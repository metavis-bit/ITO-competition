export const OUTPUT_ARTIFACT_TYPES = [
  'pptx',
  'docx',
  'game_html',
  'animation_html',
] as const;

export const DEFAULT_OUTPUT_ARTIFACT_TYPES = [
  'pptx',
  'docx',
] as const satisfies readonly (typeof OUTPUT_ARTIFACT_TYPES[number])[];

export type OutputArtifactType = (typeof OUTPUT_ARTIFACT_TYPES)[number];

export function normalizeOutputTypes(
  input?: readonly string[] | null,
): OutputArtifactType[] {
  if (!input || input.length === 0) {
    return [...DEFAULT_OUTPUT_ARTIFACT_TYPES];
  }

  const allowed = new Set<string>(OUTPUT_ARTIFACT_TYPES);
  const picked: OutputArtifactType[] = [];

  for (const item of input) {
    if (typeof item !== 'string') continue;
    if (!allowed.has(item)) continue;
    if (picked.includes(item as OutputArtifactType)) continue;
    picked.push(item as OutputArtifactType);
  }

  return picked.length > 0 ? picked : [...DEFAULT_OUTPUT_ARTIFACT_TYPES];
}
