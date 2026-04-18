import { ScanLine, Search, Bot, FileText, LayoutPanelLeft, Clapperboard } from 'lucide-react';
import { useSettingsStore } from '@/lib/store/settings';
import type { OutputArtifactType } from '@/lib/types/output-types';
import type { BackendJobStatus } from '@/lib/types/backend';
import type {
  SceneOutline,
  UserRequirements,
  PdfImage,
  ImageMapping,
} from '@/lib/types/generation';

// Session state stored in sessionStorage
export interface GenerationSessionState {
  sessionId: string;
  requirements: UserRequirements;
  pdfText: string;
  pdfImages?: PdfImage[];
  imageStorageIds?: string[];
  imageMapping?: ImageMapping;
  sceneOutlines?: SceneOutline[] | null;
  currentStep: 'generating' | 'complete';
  // PDF deferred parsing fields
  pdfStorageKey?: string;
  pdfFileName?: string;
  pdfProviderId?: string;
  pdfProviderConfig?: { apiKey?: string; baseUrl?: string };
  referenceFiles?: Array<{
    storageKey: string;
    fileName: string;
    mimeType: string;
    size: number;
    teacherNote?: string;
  }>;
  // Web search context
  researchContext?: string;
  researchSources?: Array<{ title: string; url: string }>;
  // Backend integration context (RAG reference index binding)
  backendSessionId?: string;
  backendReferenceIndex?: string;
  backendReferenceIndexes?: string[];
  outputTypes?: OutputArtifactType[];
  jobId?: string;
  jobStatus?: BackendJobStatus;
  jobStage?: string;
  jobProgress?: number;
  jobError?: string | null;
}

export type GenerationStep = {
  id: string;
  title: string;
  description: string;
  icon: React.ElementType;
  type: 'analysis' | 'writing' | 'visual';
};

export const ALL_STEPS: GenerationStep[] = [
  {
    id: 'pdf-analysis',
    title: 'generation.analyzingPdf',
    description: 'generation.analyzingPdfDesc',
    icon: ScanLine,
    type: 'analysis',
  },
  {
    id: 'web-search',
    title: 'generation.webSearching',
    description: 'generation.webSearchingDesc',
    icon: Search,
    type: 'analysis',
  },
  {
    id: 'agent-generation',
    title: 'generation.agentGeneration',
    description: 'generation.agentGenerationDesc',
    icon: Bot,
    type: 'writing',
  },
  {
    id: 'outline',
    title: 'generation.generatingOutlines',
    description: 'generation.generatingOutlinesDesc',
    icon: FileText,
    type: 'writing',
  },
  {
    id: 'slide-content',
    title: 'generation.generatingSlideContent',
    description: 'generation.generatingSlideContentDesc',
    icon: LayoutPanelLeft,
    type: 'visual',
  },
  {
    id: 'actions',
    title: 'generation.generatingActions',
    description: 'generation.generatingActionsDesc',
    icon: Clapperboard,
    type: 'visual',
  },
];

export const getActiveSteps = (session: GenerationSessionState | null) => {
  return ALL_STEPS.filter((step) => {
    if (step.id === 'pdf-analysis') return !!session?.pdfStorageKey;
    if (step.id === 'web-search') return !!session?.requirements?.webSearch;
    if (step.id === 'agent-generation') return useSettingsStore.getState().agentMode === 'auto';
    return true;
  });
};




