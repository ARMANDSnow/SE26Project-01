export type WikiSection = {
  id?: number;
  paper_id?: number;
  section: string;
  title: string;
  content: string;
  updated_at?: string;
};

export type User = {
  id: number;
  username: string;
};

export type Concept = {
  id: number;
  name: string;
  description: string;
  relation: string;
  weight: number;
};

export type Note = {
  id: number;
  paper_id: number;
  note: string;
  comment?: string;
  created_at: string;
  updated_at?: string;
};

export type PaperPdf = {
  available: boolean;
  cached: boolean;
  view_url: string | null;
  download_url: string | null;
};

export type PaperUpload = {
  visibility: "private" | "public";
  provenance: "user_upload" | "legacy_upload";
  moderation_status: "unreviewed" | "approved" | "rejected";
  owned_by_current_user: boolean;
  original_filename?: string | null;
};

export type Paper = {
  id: number;
  source?: "arxiv" | "usenix" | "sigops" | "upload" | string;
  source_id: string;
  source_url?: string;
  venue?: string;
  pdf: PaperPdf;
  title: string;
  authors: string[];
  abstract: string;
  categories: string[];
  primary_category: string;
  published_at: string;
  updated_at?: string;
  processing_status: "pending" | "processed" | "failed";
  is_favorite: boolean;
  upload?: PaperUpload | null;
  created_at?: string;
  wiki?: WikiSection[];
  concepts?: Concept[];
  notes?: Note[];
  document?: PaperDocument | null;
  summaries?: PaperSummary[];
};

export type PaperDocument = {
  parser_name: string;
  parser_version?: string;
  source_hash?: string;
  content_markdown: string;
  token_count: number;
  status: "pending" | "processing" | "completed" | "failed";
  error?: string;
  parsed_at?: string;
  updated_at?: string;
};

export type PaperChunk = {
  id: number;
  paper_id: number;
  source_hash: string;
  chunk_index: number;
  heading: string;
  content: string;
  char_start: number;
  char_end: number;
  token_count: number;
  created_at: string;
};

export type PaperSummary = {
  id: number;
  paper_id?: number;
  content: string;
  model: string;
  prompt_version: string;
  source_hash?: string;
  is_active: boolean | number;
  created_at: string;
};

export type ChatThread = {
  id: string;
  paper_id: number | null;
  title: string;
  active_leaf_id?: string;
  message_token_limit: number;
  archived: boolean | number;
  created_at: string;
  updated_at: string;
};

export type ChatMessageRow = {
  id: string;
  parent_id?: string;
  source_message_id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  status: "running" | "complete" | "failed";
  created_at: string;
};

export type ChatMessageRepository = {
  headId?: string;
  messages: ChatMessageRow[];
};

export type ResearchRunStatus =
  | "queued"
  | "running"
  | "waiting_input"
  | "paused"
  | "completed"
  | "failed"
  | "cancelling"
  | "cancelled";

export type ResearchStepStatus =
  | "queued"
  | "running"
  | "waiting_input"
  | "paused"
  | "completed"
  | "failed"
  | "skipped"
  | "cancelled";

export type ResearchStep = {
  id: string;
  run_id: string;
  step_key: string;
  step_type: string;
  title: string;
  agent_name: string;
  status: ResearchStepStatus;
  position: number;
  attempt_count: number;
  max_attempts: number;
  output: Record<string, unknown>;
  started_at?: string | null;
  completed_at?: string | null;
};

export type ResearchDecision = {
  id: string;
  run_id: string;
  step_id?: string | null;
  question: string;
  options: Array<{ id: string; label: string; description?: string }>;
  recommended_option?: string | null;
  status: "pending" | "resolved" | "cancelled";
  answer?: { option_id: string } | null;
  created_at: string;
  resolved_at?: string | null;
};

export type ResearchRun = {
  id: string;
  user_id: number;
  thread_id?: string | null;
  title: string;
  goal: string;
  mode: "harness" | "topic" | "paper";
  status: ResearchRunStatus;
  requested_action?: "pause" | "cancel" | null;
  state_version: number;
  plan_version: number;
  budget: Record<string, unknown>;
  usage: Record<string, unknown>;
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  updated_at: string;
  completed_at?: string | null;
  steps?: ResearchStep[];
  decisions?: ResearchDecision[];
  latest_event_id?: number;
};

export type ResearchEvent = {
  id: number;
  run_id: string;
  step_id?: string | null;
  event_type: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type Stats = {
  papers: number;
  processed: number;
  favorites: number;
  concepts: number;
  notes: number;
  categories: Array<{ category: string; count: number }>;
};

export type IngestResult = {
  count: number;
  fetched_count: number;
  duplicate_count: number;
  paper_ids: number[];
};

export type Subscription = {
  id: number;
  topic: string;
  created_at: string;
};

export type WikiSearchResult = {
  id: number;
  paper_id: number;
  paper_title: string;
  source: string;
  source_id: string;
  source_url?: string;
  primary_category: string;
  section: string;
  section_title: string;
  content: string;
  score: number;
  evidence_id?: string;
  chunk_id?: number;
  chunk_index?: number;
  paper_source?: string;
  source_type?: string;
  pdf_view_url?: string;
  source_hash?: string;
  char_start?: number;
  char_end?: number;
  token_count?: number;
};

export type QaExecutionStep = {
  index: number;
  kind: "tool" | string;
  tool: string;
  result_count: number;
  evidence_ids: string[];
  note: string;
};

export type QaExecution = {
  mode: "agentic_real" | "classic" | string;
  status: "completed" | "fallback" | "failed" | string;
  stop_reason: string;
  tool_call_count: number;
  steps: QaExecutionStep[];
};

export type QaResponse = {
  answer: string;
  citations: WikiSearchResult[];
  confidence: number;
  agent_trace: string[];
  execution?: QaExecution;
};

export type GraphNode = {
  id: string;
  label: string;
  type: "concept" | "paper";
  description?: string;
  category?: string;
  weight: number;
};

export type GraphLink = {
  source: string;
  target: string;
  relation: string;
  weight: number;
};

export type GraphData = {
  nodes: GraphNode[];
  links: GraphLink[];
};

export type HistoryItem = {
  id: number;
  action: string;
  created_at: string;
  paper_id: number;
  title: string;
  primary_category: string;
};

export type LibraryFolder = {
  id: number;
  parent_id?: number;
  name: string;
  description: string;
  is_system: boolean;
  is_root: boolean;
  item_count: number;
  path: string;
};

export type LibraryItem = Paper & {
  library_item_id: number;
  folder_id: number;
  saved_at: string;
};

export type FolderRecommendation = {
  folder_id: number;
  folder_name: string;
  folder_path: string;
  reason: string;
};
