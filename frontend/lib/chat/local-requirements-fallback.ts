import type { BackendTeachingIntent } from '@/lib/types/backend';

export interface LocalDialogueFallbackMetadata {
  state: string;
  isComplete: boolean;
  missingFields: string[];
  collectedInfo: string;
}

export interface LocalDialogueFallbackResult {
  reply: string;
  intent: BackendTeachingIntent;
  dialogueMeta: LocalDialogueFallbackMetadata;
  intentCollected: boolean;
}

const DEFAULT_KEY_FOCUS = ['核心概念理解', '关键过程分析', '典型题型应用'];
const DEFAULT_DIFFICULTIES = ['关键步骤辨析', '易错点区分'];

function cleanText(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

function splitList(value: string): string[] {
  return value
    .split(/[、，,；;\/]/)
    .map((item) => cleanText(item))
    .filter(Boolean)
    .slice(0, 4);
}

function firstMatch(text: string, patterns: RegExp[]): string {
  for (const pattern of patterns) {
    const match = text.match(pattern);
    const value = cleanText(match?.[1] || '');
    if (value) return value;
  }
  return '';
}

function cleanTopicCandidate(value: string): string {
  return cleanText(
    value
      .replace(/^(?:关于|有关|围绕)/, '')
      .replace(/(?:的详细内容|的具体内容|的全部内容|的内容|相关内容|相关知识|知识点|课程|课件|教案)$/i, '')
      .replace(/^(?:口述|说出|描述|解释|分析|比较|归纳|总结)/, ''),
  ).slice(0, 32);
}

function inferTopic(latestUserMessage: string, corpus: string): string {
  const explicit = cleanTopicCandidate(firstMatch(corpus, [
    /(?:课题|主题|内容|知识点)[：:\s]*([^。；\n]{2,32})/i,
    /(?:讲|学习|复习|介绍|展示)([^。；\n]{2,32})/i,
    /关于([^。；\n]{2,32})/i,
    /(?:学会|理解|掌握|能够|能|说出|口述|描述|解释|分析|比较|归纳|总结|完成)([^。；\n]{2,32})/i,
  ]));
  if (explicit) return explicit;

  const candidate = cleanTopicCandidate(
    latestUserMessage
      .replace(/^(我想|想|帮我|请|麻烦|希望|需要)/, '')
      .replace(/(做|生成|设计|准备).*/, '')
      .slice(0, 24),
  );
  return candidate || '';
}

function inferAudience(corpus: string): string {
  return firstMatch(corpus, [
    /((?:高一|高二|高三|初一|初二|初三|七年级|八年级|九年级|高中|初中)[^。；\n]{0,10})/,
    /(?:给|面向|针对)([^。；\n]{2,24})(?:上课|使用|学生)?/,
  ]);
}

function inferTeachingGoal(corpus: string): string {
  return firstMatch(corpus, [
    /(?:教学目标|目标)[：:\s]*([^。；\n]{6,80})/i,
    /(?:想让学生|希望学生|让学生)([^。；\n]{6,80})/i,
    /((?:学会|理解|掌握|能够|能|说出|口述|描述|解释|分析|比较|归纳|总结|完成)[^。；\n]{4,80})/i,
  ]);
}

function inferKeyFocus(corpus: string): string[] {
  const explicit = firstMatch(corpus, [
    /(?:重点|核心内容|关键内容)[：:\s]*([^。；\n]{4,80})/i,
  ]);
  if (explicit) return splitList(explicit);
  return [];
}

function inferDifficulties(corpus: string): string[] {
  const explicit = firstMatch(corpus, [
    /(?:难点|重点难点|易错点)[：:\s]*([^。；\n]{4,80})/i,
  ]);
  if (explicit) return splitList(explicit);
  return [];
}

function inferSpecialRequirements(corpus: string): string {
  return firstMatch(corpus, [
    /(?:特殊要求|额外要求|补充要求)[：:\s]*([^。；\n]{4,120})/i,
    /(?:最好|希望|需要)([^。；\n]{6,80})/i,
  ]);
}

function summarizeIntent(intent: BackendTeachingIntent): string {
  return [
    intent.topic && `课题：${intent.topic}`,
    intent.teaching_goal && `教学目标：${intent.teaching_goal}`,
    intent.target_audience && `授课对象：${intent.target_audience}`,
    intent.key_focus?.length ? `重点：${intent.key_focus.join('、')}` : '',
    intent.difficulties?.length ? `难点：${intent.difficulties.join('、')}` : '',
    intent.special_requirements && `特殊要求：${intent.special_requirements}`,
  ]
    .filter(Boolean)
    .join('；');
}

export function buildLocalRequirementsFallback(
  latestUserMessage: string,
  existingMessages: Array<{ role: 'user' | 'assistant'; content: string }>,
  existingIntent: BackendTeachingIntent | null,
): LocalDialogueFallbackResult {
  const userCorpus = existingMessages
    .filter((message) => message.role === 'user')
    .map((message) => message.content)
    .concat(latestUserMessage)
    .join('\n');

  const nextIntent: BackendTeachingIntent = {
    topic: existingIntent?.topic || '',
    subject: '生物',
    ...(existingIntent || {}),
  };

  nextIntent.topic = nextIntent.topic || inferTopic(latestUserMessage, userCorpus);
  nextIntent.target_audience = nextIntent.target_audience || inferAudience(userCorpus);
  nextIntent.teaching_goal = nextIntent.teaching_goal || inferTeachingGoal(userCorpus);
  nextIntent.key_focus = (nextIntent.key_focus && nextIntent.key_focus.length > 0)
    ? nextIntent.key_focus
    : inferKeyFocus(userCorpus);
  nextIntent.difficulties = (nextIntent.difficulties && nextIntent.difficulties.length > 0)
    ? nextIntent.difficulties
    : inferDifficulties(userCorpus);
  nextIntent.special_requirements =
    nextIntent.special_requirements || inferSpecialRequirements(userCorpus);

  const coreReady = Boolean(
    cleanText(nextIntent.topic || '') &&
      cleanText(nextIntent.target_audience || '') &&
      cleanText(nextIntent.teaching_goal || ''),
  );

  if (coreReady && (!nextIntent.key_focus || nextIntent.key_focus.length === 0)) {
    nextIntent.key_focus = DEFAULT_KEY_FOCUS;
  }
  if (coreReady && (!nextIntent.difficulties || nextIntent.difficulties.length === 0)) {
    nextIntent.difficulties = DEFAULT_DIFFICULTIES;
  }

  const missingFields: string[] = [];
  if (!cleanText(nextIntent.topic || '')) missingFields.push('topic');
  if (!cleanText(nextIntent.teaching_goal || '')) missingFields.push('teaching_goal');
  if (!cleanText(nextIntent.target_audience || '')) missingFields.push('target_audience');

  let reply = '';
  if (missingFields[0] === 'topic') {
    reply += ' 先告诉我这节课具体要讲哪个课题或知识点，比如“DNA复制”或“减数分裂”。';
  } else if (missingFields[0] === 'teaching_goal') {
    reply += ' 我已经识别到课题了。接下来请告诉我这节课最想让学生学会什么，最好用一句完整的话描述教学目标。';
  } else if (missingFields[0] === 'target_audience') {
    reply += ' 还差授课对象信息。请补充年级或学段，例如“高一”或“高二”。';
  } else {
    reply += ` 我已经整理出当前教学意图：${summarizeIntent(nextIntent)}。如果没有补充内容，可以直接确认并生成课件。`;
  }

  return {
    reply,
    intent: nextIntent,
    intentCollected: missingFields.length === 0,
    dialogueMeta: {
      state: missingFields.length === 0 ? 'ready' : 'collecting',
      isComplete: missingFields.length === 0,
      missingFields,
      collectedInfo: summarizeIntent(nextIntent),
    },
  };
}
