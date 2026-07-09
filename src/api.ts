import type { GraphData, HistoryItem, IngestResult, Note, Paper, PaperChunk, QaResponse, Stats, Subscription, WikiSearchResult } from "./types";
import { mockGraph, mockHistory, mockPapers, mockQa, mockSearchResults, mockStats, mockSubscriptions } from "./mock";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const USE_MOCK = String(import.meta.env.VITE_USE_MOCK ?? "false").toLowerCase() === "true";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {})
    },
    ...options
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchStats(): Promise<Stats> {
  if (USE_MOCK) {
    return mockStats;
  }
  return request<Stats>("/api/stats");
}

export async function fetchPapers(params: Record<string, string | boolean | number | undefined> = {}): Promise<Paper[]> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "" && value !== false) {
      search.set(key, String(value));
    }
  });
  if (USE_MOCK) {
    return mockPapers;
  }
  const data = await request<{ items: Paper[] }>(`/api/papers?${search.toString()}`);
  return data.items;
}

export async function fetchPaperDetail(id: number): Promise<Paper> {
  if (USE_MOCK) {
    return mockPapers.find((paper) => paper.id === id) ?? mockPapers[0];
  }
  return request<Paper>(`/api/papers/${id}`);
}

export async function fetchPaperChunks(id: number, limit = 6, offset = 0): Promise<{ items: PaperChunk[]; count: number }> {
  if (USE_MOCK) {
    const paper = mockPapers.find((item) => item.id === id) ?? mockPapers[0];
    return {
      count: 1,
      items: [
        {
          id,
          paper_id: paper.id,
          source_type: "metadata",
          source_url: paper.arxiv_url,
          chunk_index: 0,
          heading: "Metadata #1",
          content: `${paper.title}\n${paper.abstract}`,
          char_start: 0,
          char_end: paper.abstract.length,
          token_count: 32,
          created_at: new Date().toISOString()
        }
      ]
    };
  }
  return request<{ items: PaperChunk[]; count: number }>(`/api/papers/${id}/chunks?limit=${limit}&offset=${offset}`);
}

export async function processPaper(id: number): Promise<Paper> {
  if (USE_MOCK) {
    const paper = mockPapers.find((item) => item.id === id) ?? mockPapers[0];
    return { ...paper, processing_status: "processed" };
  }
  const data = await request<{ paper: Paper }>(`/api/papers/${id}/process`, { method: "POST" });
  return data.paper;
}

export async function ingestArxiv(payload: { categories: string[]; keywords: string[]; max_results: number }) {
  if (USE_MOCK) {
    return { count: 0, fetched_count: 0, duplicate_count: 0, paper_ids: [] } satisfies IngestResult;
  }
  return request<IngestResult>("/api/ingest/arxiv", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function searchWiki(q: string): Promise<WikiSearchResult[]> {
  if (USE_MOCK) {
    return mockSearchResults;
  }
  const data = await request<{ items: WikiSearchResult[] }>(`/api/wiki/search?q=${encodeURIComponent(q)}&limit=8`);
  return data.items;
}

export async function askQuestion(question: string, paperIds: number[] = []): Promise<QaResponse> {
  if (USE_MOCK) {
    return mockQa;
  }
  return request<QaResponse>("/api/qa", {
    method: "POST",
    body: JSON.stringify({ question, paper_ids: paperIds })
  });
}

export async function fetchGraph(topic = ""): Promise<GraphData> {
  if (USE_MOCK) {
    return mockGraph;
  }
  return request<GraphData>(`/api/graph?topic=${encodeURIComponent(topic)}&limit=42`);
}

export async function toggleFavorite(paperId: number, favorite: boolean): Promise<Paper> {
  if (USE_MOCK) {
    const paper = mockPapers.find((item) => item.id === paperId) ?? mockPapers[0];
    return { ...paper, is_favorite: favorite };
  }
  return request<Paper>("/api/library/favorites", {
    method: "POST",
    body: JSON.stringify({ paper_id: paperId, favorite })
  });
}

export async function addNote(paperId: number, note: string, comment = ""): Promise<Note> {
  if (USE_MOCK) {
    return {
      id: Date.now(),
      paper_id: paperId,
      note,
      comment,
      created_at: new Date().toISOString()
    };
  }
  return request<Note>("/api/notes", {
    method: "POST",
    body: JSON.stringify({ paper_id: paperId, note, comment })
  });
}

export async function fetchHistory(): Promise<HistoryItem[]> {
  if (USE_MOCK) {
    return mockHistory;
  }
  const data = await request<{ items: HistoryItem[] }>("/api/history?limit=30");
  return data.items;
}

export async function fetchSubscriptions(): Promise<Subscription[]> {
  if (USE_MOCK) {
    return mockSubscriptions;
  }
  const data = await request<{ items: Subscription[] }>("/api/subscriptions");
  return data.items;
}

export async function addSubscription(topic: string): Promise<Subscription> {
  if (USE_MOCK) {
    return {
      id: Date.now(),
      topic,
      created_at: new Date().toISOString()
    };
  }
  return request<Subscription>("/api/subscriptions", {
    method: "POST",
    body: JSON.stringify({ topic })
  });
}
