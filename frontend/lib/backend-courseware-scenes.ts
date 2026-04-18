import { nanoid } from 'nanoid';
import type { Action } from '@/lib/types/action';
import type { InteractiveResourceKind, Scene, Stage } from '@/lib/types/stage';
import type {
  BackendArtifact,
  BackendCoursewareContent,
  BackendPlanSlide,
} from '@/lib/types/backend-courseware';
import { getBiologyImageUrl, matchBiologyImage } from '@/lib/utils/biology-images';

type BackendResourceArtifactType = 'docx' | 'game_html' | 'animation_html';

export function isBackendCoursewareContent(content: unknown): content is BackendCoursewareContent {
  return !!content && typeof content === 'object' && 'artifacts' in content;
}

export function getArtifactDisplayLabel(type: string): string {
  switch (type) {
    case 'pptx':
      return 'PPT';
    case 'docx':
      return '教案';
    case 'game_html':
      return '互动游戏';
    case 'animation_html':
      return '概念动画';
    default:
      return type;
  }
}

function appendVersionParam(url: string, versionId?: string | null): string {
  if (!versionId?.trim()) {
    return url;
  }
  return `${url}&version_id=${encodeURIComponent(versionId)}`;
}

export function buildArtifactPreviewUrl(
  sessionId: string,
  artifactType: string,
  versionId?: string | null,
): string {
  return appendVersionParam(
    `/api/artifacts/preview?session_id=${encodeURIComponent(sessionId)}&artifact_type=${encodeURIComponent(artifactType)}`,
    versionId,
  );
}

export function buildArtifactDownloadUrl(
  sessionId: string,
  artifactType: string,
  versionId?: string | null,
): string {
  return appendVersionParam(
    `/api/artifacts/download?sessionId=${encodeURIComponent(sessionId)}&type=${encodeURIComponent(artifactType)}`,
    versionId,
  );
}

function buildSpeechAction(text: string): Action[] {
  return [
    {
      id: `action_${nanoid(8)}`,
      type: 'speech',
      title: '场景讲解',
      text,
    },
  ];
}

function buildSlideSpeech(slide: BackendPlanSlide): string {
  const parts = [
    slide.notes?.trim(),
    slide.bullet_points?.filter(Boolean).join('；'),
    slide.visual_suggestion?.trim(),
  ].filter(Boolean);
  return parts.join('。') || slide.title;
}

function buildSlideScene(slide: BackendPlanSlide, stageId: string): Scene {
  const description = slide.notes?.trim() || slide.visual_suggestion?.trim() || '';
  const matchedImage = matchBiologyImage(
    slide.title,
    `${description}\n${slide.bullet_points.join('\n')}`,
  );
  const hasImage = !!matchedImage;
  const imageUrl = matchedImage ? getBiologyImageUrl(matchedImage) : '';
  const imageHeight = slide.layout === 'cover' ? 300 : 420;
  const textElements: Array<{
    id: string;
    type: 'text';
    left: number;
    top: number;
    width: number;
    height: number;
    content: string;
    rotate: number;
    defaultFontName: string;
    defaultColor: string;
  }> = [];

  textElements.push({
    id: nanoid(),
    type: 'text',
    left: hasImage ? 48 : 72,
    top: slide.layout === 'cover' ? 96 : 68,
    width: hasImage ? 480 : 856,
    height: 90,
    content: `<p style="text-align:${slide.layout === 'cover' ? 'center' : hasImage ? 'left' : 'center'};font-size:${slide.layout === 'cover' ? 34 : 30}px;font-weight:700;color:#174f37;line-height:1.25">${slide.title}</p>`,
    rotate: 0,
    defaultFontName: 'Microsoft YaHei',
    defaultColor: '#174f37',
  });

  if (description) {
    textElements.push({
      id: nanoid(),
      type: 'text',
      left: hasImage ? 48 : 96,
      top: slide.layout === 'cover' ? 200 : 168,
      width: hasImage ? 472 : 808,
      height: slide.layout === 'cover' ? 96 : 120,
      content: `<p style="text-align:${slide.layout === 'cover' ? 'center' : 'left'};font-size:17px;color:#456154;line-height:1.8">${description}</p>`,
      rotate: 0,
      defaultFontName: 'Microsoft YaHei',
      defaultColor: '#456154',
    });
  }

  if (slide.bullet_points?.length) {
    const bulletHtml = slide.bullet_points.map((point) => `<li>${point}</li>`).join('');
    textElements.push({
      id: nanoid(),
      type: 'text',
      left: hasImage ? 48 : 92,
      top: slide.layout === 'cover' ? 320 : description ? 290 : 180,
      width: hasImage ? 470 : 816,
      height: hasImage ? 180 : 220,
      content: `<ul style="font-size:16px;color:#4b5563;line-height:1.9;padding-left:20px">${bulletHtml}</ul>`,
      rotate: 0,
      defaultFontName: 'Microsoft YaHei',
      defaultColor: '#4b5563',
    });
  }

  const imageElements = hasImage
    ? [
        {
          id: nanoid(),
          type: 'image' as const,
          left: 558,
          top: slide.layout === 'cover' ? 122 : 72,
          width: 360,
          height: imageHeight,
          src: imageUrl,
          rotate: 0,
          fixedRatio: true,
        },
      ]
    : [];

  return {
    id: nanoid(),
    stageId,
    type: 'slide',
    title: slide.title,
    order: Math.max(0, (slide.slide_number || 1) - 1),
    content: {
      type: 'slide',
      canvas: {
        id: nanoid(),
        viewportSize: 1000,
        viewportRatio: 0.5625,
        theme: {
          backgroundColor: '#f3fbf7',
          themeColors: ['#174f37', '#2c7a57', '#53a779', '#9ad3b0', '#dff5e7'],
          fontColor: '#174f37',
          fontName: 'Microsoft YaHei',
          outline: { color: '#2c7a57', width: 1, style: 'solid' },
          shadow: { h: 0, v: 2, blur: 8, color: '#00000012' },
        },
        elements: [...textElements, ...imageElements],
        background: { type: 'solid', color: '#f3fbf7' },
      },
    },
    actions: buildSpeechAction(buildSlideSpeech(slide)),
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
}

function buildInteractiveScene(params: {
  title: string;
  artifact: BackendArtifact;
  sessionId: string;
  versionId?: string | null;
  stageId: string;
  order: number;
  description: string;
  resourceKind: InteractiveResourceKind;
}): Scene {
  return {
    id: nanoid(),
    stageId: params.stageId,
    type: 'interactive',
    title: params.title,
    order: params.order,
    content: {
      type: 'interactive',
      url: buildArtifactPreviewUrl(params.sessionId, params.artifact.type, params.versionId),
      resourceKind: params.resourceKind,
      artifactType: params.artifact.type as BackendResourceArtifactType,
      versionId: params.versionId || undefined,
    },
    actions: buildSpeechAction(params.description),
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
}

function findArtifact(
  artifacts: BackendArtifact[],
  type: BackendResourceArtifactType,
): BackendArtifact | undefined {
  return artifacts.find(
    (artifact) => artifact.type === type && !artifact.error && !!artifact.file_path,
  );
}

export function buildBackendCoursewareScenes(
  content: BackendCoursewareContent,
  stageId: string,
): Scene[] {
  const scenes: Scene[] = [];
  const slides = content.plan?.slides || [];
  const sessionId = content.sessionId;
  const versionId = content.versionId;

  if (slides.length > 0) {
    scenes.push(...slides.map((slide) => buildSlideScene(slide, stageId)));
  }

  const nextOrderBase = slides.length;
  const lessonPlanArtifact = findArtifact(content.artifacts, 'docx');
  if (lessonPlanArtifact) {
    scenes.push(
      buildInteractiveScene({
        title: '教案',
        artifact: lessonPlanArtifact,
        sessionId,
        versionId,
        stageId,
        order: nextOrderBase,
        description: '这里展示本次生成的完整教案，便于备课、讲授和课堂复盘。',
        resourceKind: 'lesson_plan',
      }),
    );
  }

  const gameArtifact = findArtifact(content.artifacts, 'game_html');
  if (gameArtifact) {
    scenes.push(
      buildInteractiveScene({
        title: '互动游戏',
        artifact: gameArtifact,
        sessionId,
        versionId,
        stageId,
        order: nextOrderBase + (lessonPlanArtifact ? 1 : 0),
        description: '这里展示本次生成的互动游戏，帮助学生在练习中巩固核心知识点。',
        resourceKind: 'game',
      }),
    );
  }

  const animationArtifact = findArtifact(content.artifacts, 'animation_html');
  if (animationArtifact) {
    scenes.push(
      buildInteractiveScene({
        title: '概念动画',
        artifact: animationArtifact,
        sessionId,
        versionId,
        stageId,
        order: nextOrderBase + (lessonPlanArtifact ? 1 : 0) + (gameArtifact ? 1 : 0),
        description: '这里展示本次生成的概念动画，帮助学生理解过程、结构和变化机理。',
        resourceKind: 'animation',
      }),
    );
  }

  if (scenes.length === 0) {
    scenes.push({
      id: nanoid(),
      stageId,
      type: 'slide',
      title: '课件内容',
      order: 0,
      content: {
        type: 'slide',
        canvas: {
          id: nanoid(),
          viewportSize: 1000,
          viewportRatio: 0.5625,
          theme: {
            backgroundColor: '#f3fbf7',
            themeColors: ['#174f37', '#2c7a57', '#53a779', '#9ad3b0', '#dff5e7'],
            fontColor: '#174f37',
            fontName: 'Microsoft YaHei',
            outline: { color: '#2c7a57', width: 1, style: 'solid' },
            shadow: { h: 0, v: 2, blur: 8, color: '#00000012' },
          },
          elements: [
            {
              id: nanoid(),
              type: 'text',
              left: 100,
              top: 180,
              width: 800,
              height: 140,
              content:
                '<p style="text-align:center;font-size:32px;font-weight:700;color:#174f37">后端已返回产物，但未生成可展示的页面数据</p>',
              rotate: 0,
              defaultFontName: 'Microsoft YaHei',
              defaultColor: '#174f37',
            },
          ],
          background: { type: 'solid', color: '#f3fbf7' },
        },
      },
      actions: buildSpeechAction(
        '后端已完成生成，请使用页面中的资源入口查看课件、教案、游戏和动画。',
      ),
      createdAt: Date.now(),
      updatedAt: Date.now(),
    });
  }

  return scenes.sort((a, b) => a.order - b.order);
}

export function buildBackendStagePatch(content: BackendCoursewareContent): Pick<
  Stage,
  | 'backendSessionId'
  | 'backendVersionId'
  | 'backendArtifacts'
  | 'backendPlan'
  | 'backendErrors'
  | 'backendMissingArtifacts'
> {
  return {
    backendSessionId: content.sessionId,
    backendVersionId: content.versionId || undefined,
    backendArtifacts: content.artifacts,
    backendPlan: content.plan,
    backendErrors: content.errors,
    backendMissingArtifacts: content.missingArtifacts,
  };
}
