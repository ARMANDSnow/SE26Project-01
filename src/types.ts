export type WikiSection = {
  id?: number;
  paper_id?: number;
  section: string;
  title: string;
  content: string;
  updated_at?: string;
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

export type Paper = {
  id: number;
  arxiv_id: string;
  source?: "arxiv" | "usenix" | "sigops" | "upload" | string;
  source_id?: string;
  source_url?: string;
  venue?: string;
  file_url?: string;
  title: string;
  authors: string[];
  abstract: string;
  categories: string[];
  primary_category: string;
  published_at: string;
  updated_at?: string;
  pdf_url?: string;
  arxiv_url?: string;
  doi?: string;
  processing_status: "pending" | "processed" | "failed";
  reading_status: "unread" | "reading" | "done";
  is_favorite: boolean;
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
  paper_id: number;
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
  arxiv_id: string;
  arxiv_url?: string;
  pdf_url?: string;
  primary_category: string;
  section: string;
  section_title: string;
  content: string;
  score: number;
};

export type QaResponse = {
  answer: string;
  citations: WikiSearchResult[];
  confidence: number;
  agent_trace: string[];
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
