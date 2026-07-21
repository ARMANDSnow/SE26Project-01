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
  source_available: boolean;
  view_url: string | null;
  download_url: string | null;
};

export type PaperPreparation = {
  status: "not_queued" | "queued" | "download" | "parse" | "index" | "retry_wait" | "ready" | "failed";
  attempt_count: number;
  max_attempts: number;
  error_code?: string | null;
  error_message?: string | null;
  updated_at?: string | null;
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
  preparation: PaperPreparation;
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
  content_parts: ChatContentPart[];
  status: "running" | "complete" | "failed";
  created_at: string;
};

export type ChatTextPart = { type: "text"; text: string };
export type ResearchRunDataPart = {
  type: "data";
  name: "research-run";
  data: { run_id: string };
};
export type ChatContentPart = ChatTextPart | ResearchRunDataPart;

export type ChatRouteMode = "auto" | "normal" | "deep_research";
export type ChatRouteResponse =
  | { route: "normal_chat"; reason: "explicit" | "deterministic" | "model" }
  | {
      route: "research_run";
      reason: "explicit" | "deterministic" | "model";
      run: ResearchRun;
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

export type ResearchBudget = {
  kind: "harness" | "topic" | "project";
  max_candidates?: number;
  max_fulltext_papers?: number;
  max_model_calls?: number;
  max_tool_calls?: number;
  max_wall_clock_seconds?: number;
  external_calls?: number;
};

export type ResearchUsage = {
  candidate_papers?: number;
  fulltext_papers?: number;
  model_calls?: number;
  tool_calls?: number;
  successful_calls?: number;
  failed_calls?: number;
  wall_clock_seconds?: number;
  external_calls?: number;
};

export type ResearchBrief = {
  topic: string;
  research_questions: string[];
  scope: string;
  inclusion_criteria: string[];
  exclusion_criteria: string[];
  date_range: { start_year?: number | null; end_year?: number | null };
  preferred_sources: Array<"local" | "arxiv">;
  output_language: string;
  constraints: string[];
  schema_version: 1;
};

export type ChunkEvidenceRef = {
  evidence_id?: string | null;
  chunk_id: number;
  paper_id: number;
  source_hash: string;
  chunk_index: number;
  char_start: number;
  char_end: number;
  heading: string;
};

export type PaperBrief = {
  paper_id: number;
  source: string;
  source_id: string;
  title: string;
  authors: string[];
  year: number;
  research_question: string;
  method: string;
  dataset: string;
  experiments: string;
  key_findings: string[];
  limitations: string[];
  relevance: string;
  evidence_ids: ChunkEvidenceRef[];
  source_hash: string;
  schema_version: 1;
};

export type ResearchArtifactType =
  | "research_brief" | "search_queries" | "candidate_papers"
  | "screening_result" | "paper_brief" | "extraction_result"
  | "synthesis_plan" | "comparison_matrix" | "synthesis_claims"
  | "citation_registry" | "research_report" | "citation_validation_result"
  | "research_landscape_plan" | "topic_clusters" | "research_timeline"
  | "research_graph" | "project_analysis_validation";

export type SynthesisPlan = {
  topic: string;
  research_questions: string[];
  comparison_dimensions: string[];
  synthesis_strategy: string;
  expected_outputs: string[];
  constraints: string[];
  schema_version: 1;
};

export type CitedStatement = { statement_id: string; text: string; citation_keys: string[] };
export type LandscapeCitedStatement = { text: string; citation_keys: string[] };
export type ComparisonMatrix = {
  dimensions: string[];
  papers: Array<{ paper_id: number; title: string }>;
  cells: Array<{ cell_id: string; dimension: string; paper_id: number; value: string; citation_keys: string[]; evidence_ids: string[] }>;
  agreements: CitedStatement[];
  disagreements: CitedStatement[];
  missing_evidence: Array<{ dimension: string; paper_id?: number | null; uncertainty: string }>;
  schema_version: 1;
};
export type SynthesisClaim = {
  claim_id: string;
  claim: string;
  claim_type: "finding" | "agreement" | "disagreement" | "limitation" | "gap";
  confidence: number;
  supporting_citations: string[];
  contradicting_citations: string[];
  covered_paper_ids: number[];
  caveats: string[];
  schema_version: 1;
};
export type SynthesisClaims = { claims: SynthesisClaim[]; schema_version: 1 };
export type CitationValidationResult = {
  valid_citation_keys: string[];
  stale_citation_keys: string[];
  inaccessible_citation_keys: string[];
  invalid_citation_keys: string[];
  verified_claim_ids: string[];
  schema_version: 1;
};
export type ResearchReport = {
  title: string;
  topic: string;
  executive_summary: CitedStatement[];
  research_questions: string[];
  findings: CitedStatement[];
  agreements: CitedStatement[];
  disagreements: CitedStatement[];
  limitations: string[];
  research_gaps: string[];
  conclusion: CitedStatement[];
  citation_keys: string[];
  generated_from_artifact_versions: Record<string, number>;
  schema_version: 1;
};

export type ResearchCitationStatus = "valid" | "stale" | "inaccessible" | "invalid";
export type ResearchCitation = {
  id: string;
  run_id: string;
  artifact_id: string;
  artifact_version: number;
  citation_key: string;
  status: ResearchCitationStatus;
  claim_id?: string;
  paper_id?: number;
  chunk_id?: number;
  evidence_id?: string;
  source?: string;
  source_id?: string;
  source_hash?: string;
  heading?: string;
  char_start?: number;
  char_end?: number;
  quote_hash?: string;
  excerpt?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type ResearchArtifact = {
  id: string;
  run_id: string;
  paper_id?: number | null;
  artifact_type: ResearchArtifactType;
  schema_version: number;
  source_step_id: string;
  version: number;
  status: "draft" | "completed" | "failed" | "stale";
  content: Record<string, unknown>;
  source_hash?: string | null;
  is_current: boolean;
  created_at: string;
  updated_at: string;
};

export type ResearchRunPaperStage =
  | "candidate" | "selected" | "excluded" | "fulltext_ready" | "read" | "extracted";

export type ResearchRunPaper = {
  run_id: string;
  paper_id: number;
  source_step_id?: string | null;
  stage: ResearchRunPaperStage;
  rank?: number | null;
  score?: number | null;
  inclusion_reason?: string | null;
  exclusion_reason?: string | null;
  source: string;
  source_id: string;
  source_hash?: string | null;
  title: string;
  authors: string[];
  abstract: string;
  published_at: string;
  primary_category: string;
  source_url?: string | null;
  processing_status: string;
  created_at: string;
  updated_at: string;
};

export type ResearchToolCallSummary = {
  tool: string;
  status: "completed" | "failed" | "reused";
  attempt: number;
  summary: string;
  duration_ms: number;
  error_code?: string | null;
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
  project_id?: string | null;
  title: string;
  goal: string;
  mode: "harness" | "topic" | "paper" | "project";
  status: ResearchRunStatus;
  requested_action?: "pause" | "cancel" | null;
  state_version: number;
  plan_version: number;
  budget: ResearchBudget;
  usage: ResearchUsage;
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

export type ResearchProjectStatus = "active" | "archived";
export type ResearchProjectItemType = "run" | "paper" | "research_report";
export type ProjectDependencyStatus = "current" | "stale" | "inaccessible";

export type ResearchProject = {
  id: string;
  owner_user_id: number;
  title: string;
  description: string;
  status: ResearchProjectStatus;
  item_count?: number;
  current_item_count?: number;
  stale_item_count?: number;
  inaccessible_item_count?: number;
  latest_analysis_run_id?: string | null;
  latest_analysis_status?: ResearchRunStatus | null;
  created_at: string;
  updated_at: string;
};

export type ResearchProjectItem = {
  id: string;
  project_id: string;
  item_type: ResearchProjectItemType;
  run_id?: string | null;
  paper_id?: number | null;
  artifact_id?: string | null;
  artifact_version?: number | null;
  source_run_id?: string | null;
  source_hash_snapshot?: string | null;
  position: number;
  dependency_status: ProjectDependencyStatus;
  title?: string | null;
  subtitle?: string | null;
  added_at: string;
  updated_at: string;
};

export type ResearchProjectItemInput =
  | { item_type: "run"; run_id: string }
  | { item_type: "paper"; paper_id: number }
  | { item_type: "research_report"; artifact_id: string; artifact_version: number };

export type ResearchProjectCoverage = {
  status: "ready" | "limited" | "blocked";
  total_items: number;
  current_items: number;
  stale_items: number;
  inaccessible_items: number;
  paper_count: number;
  report_count: number;
  valid_citation_count: number;
  missing_inputs: string[];
  warnings: string[];
  can_analyze: boolean;
  updated_at: string;
};

export type ResearchLandscapePlan = {
  project_id: string;
  topic: string;
  research_questions: string[];
  selected_item_ids: string[];
  clustering_dimensions: string[];
  timeline_dimensions: string[];
  graph_relation_types: string[];
  constraints: string[];
  schema_version: number;
};

export type TopicCluster = {
  cluster_id: string;
  label: string;
  summary: string;
  paper_ids: number[];
  claim_ids: string[];
  citation_keys: string[];
  summary_citation_keys: string[];
  distinguishing_features: LandscapeCitedStatement[];
  uncertainties: string[];
  schema_version: number;
};

export type TopicClusters = {
  clusters: TopicCluster[];
  unclassified_paper_ids: number[];
  citation_keys: string[];
  uncertainties: string[];
  schema_version: number;
};

export type ResearchTimelineEvent = {
  event_id: string;
  date?: string | null;
  date_range?: { start?: string | null; end?: string | null } | null;
  event_type: string;
  title: string;
  description: string;
  paper_ids: number[];
  claim_ids: string[];
  citation_keys: string[];
  confidence: number;
};

export type ResearchTimeline = {
  events: ResearchTimelineEvent[];
  periods: Array<{ period_id: string; date_range: { start: string; end: string }; title: string; description: string; event_ids: string[]; citation_keys: string[] }>;
  turning_points: LandscapeCitedStatement[];
  unresolved_questions: string[];
  citation_keys: string[];
  schema_version: number;
};

export type ResearchGraphNodeType = "project" | "run" | "paper" | "report" | "topic_cluster" | "synthesis_claim";
export type ResearchGraphEdgeType = "contains" | "generated_from" | "cites" | "supports" | "contradicts" | "belongs_to_cluster" | "precedes" | "influences";

export type ResearchGraphNode = {
  node_id: string;
  node_type: ResearchGraphNodeType;
  label: string;
  entity_ref: string;
  status: "valid" | "stale" | "inaccessible";
};

export type ResearchGraphEdge = {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  relation_type: ResearchGraphEdgeType;
  citation_keys: string[];
  status: "valid" | "stale" | "inaccessible";
};

export type ResearchGraph = {
  nodes: ResearchGraphNode[];
  edges: ResearchGraphEdge[];
  citation_keys: string[];
  schema_version: number;
};

export type ProjectAnalysisValidation = {
  validated_cluster_ids: string[];
  validated_timeline_event_ids: string[];
  validated_edge_ids: string[];
  stale_dependencies: string[];
  inaccessible_dependencies: string[];
  coverage_summary: { accessible_item_count: number; paper_count: number; report_count: number; valid_citation_count: number; limited: boolean };
  warnings: string[];
  schema_version: number;
};

export type ResearchProjectArtifactType =
  | "research_landscape_plan" | "topic_clusters" | "research_timeline"
  | "research_graph" | "project_analysis_validation";

export type ResearchProjectArtifact<T extends object = Record<string, unknown>> = {
  id: string;
  project_id: string;
  artifact_type: ResearchProjectArtifactType;
  version: number;
  status: "completed" | "failed" | "stale" | "inaccessible";
  dependency_status: ProjectDependencyStatus;
  is_current: boolean;
  content?: T | null;
  input_item_ids?: string[];
  citation_keys?: string[];
  created_at: string;
  updated_at: string;
};

export type ResearchProjectAnalysis = {
  project_id: string;
  run?: ResearchRun | null;
  tool_summaries: ResearchToolCallSummary[];
};

export type ProjectEvidenceItem = {
  citation_id: string;
  citation_label: string;
  status: ResearchCitationStatus;
  paper_id?: number | null;
  paper_title?: string | null;
  heading?: string | null;
  excerpt?: string | null;
  chunk_id?: number | null;
  char_start?: number | null;
  char_end?: number | null;
};

export type ProjectEntityEvidence = {
  entity_id: string;
  entity_kind: "node" | "edge";
  dependency_status: ProjectDependencyStatus;
  citations: ProjectEvidenceItem[];
};

export type ResearchProjectBacklink = {
  project_id: string;
  project_title: string;
  project_status: ResearchProjectStatus;
  item_id: string;
};

export type ResearchReportLibraryItem = {
  artifact_id: string;
  artifact_version: number;
  run_id: string;
  run_title: string;
  title: string;
  topic: string;
  status: "completed" | "stale" | "inaccessible";
  is_current: boolean;
  created_at: string;
  updated_at: string;
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
  queued_count: number;
  active_count: number;
  ready_count: number;
};

export type PaperProcessingEnqueueResult = {
  disposition: "queued" | "active" | "ready" | "failed";
  preparation: PaperPreparation;
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
