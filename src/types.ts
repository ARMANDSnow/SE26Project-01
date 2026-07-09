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

export type PaperChunk = {
  id: number;
  paper_id: number;
  source_type: "html" | "pdf" | "metadata" | string;
  source_url?: string;
  chunk_index: number;
  heading: string;
  content: string;
  char_start: number;
  char_end: number;
  token_count: number;
  created_at: string;
};

export type Paper = {
  id: number;
  arxiv_id: string;
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
  chunk_count?: number;
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
  chunk_id?: number;
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
  source?: "chunk" | "wiki" | string;
  source_type?: "html" | "pdf" | "metadata" | string;
  source_url?: string;
  chunk_index?: number;
  heading?: string;
  char_start?: number;
  char_end?: number;
  token_count?: number;
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
