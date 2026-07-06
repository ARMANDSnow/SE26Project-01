import type { GraphData, HistoryItem, Note, Paper, QaResponse, Stats, WikiSearchResult } from "./types";
import { mockGraph, mockHistory, mockPapers, mockQa, mockSearchResults, mockStats } from "./mock";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

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
  try {
    return await request<Stats>("/api/stats");
  } catch {
    return mockStats;
  }
}

export async function fetchPapers(params: Record<string, string | boolean | number | undefined> = {}): Promise<Paper[]> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "" && value !== false) {
      search.set(key, String(value));
    }
  });
  try {
    const data = await request<{ items: Paper[] }>(`/api/papers?${search.toString()}`);
    return data.items;
  } catch {
    return mockPapers;
  }
}

export async function fetchPaperDetail(id: number): Promise<Paper> {
  try {
    return await request<Paper>(`/api/papers/${id}`);
  } catch {
    return mockPapers.find((paper) => paper.id === id) ?? mockPapers[0];
  }
}

export async function processPaper(id: number): Promise<Paper> {
  const data = await request<{ paper: Paper }>(`/api/papers/${id}/process`, { method: "POST" });
  return data.paper;
}

export async function ingestArxiv(payload: { categories: string[]; keywords: string[]; max_results: number }) {
  return request<{ count: number; paper_ids: number[] }>("/api/ingest/arxiv", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function searchWiki(q: string): Promise<WikiSearchResult[]> {
  try {
    const data = await request<{ items: WikiSearchResult[] }>(`/api/wiki/search?q=${encodeURIComponent(q)}&limit=8`);
    return data.items;
  } catch {
    return mockSearchResults;
  }
}

export async function askQuestion(question: string, paperIds: number[] = []): Promise<QaResponse> {
  try {
    return await request<QaResponse>("/api/qa", {
      method: "POST",
      body: JSON.stringify({ question, paper_ids: paperIds })
    });
  } catch {
    return mockQa;
  }
}

export async function fetchGraph(topic = ""): Promise<GraphData> {
  try {
    return await request<GraphData>(`/api/graph?topic=${encodeURIComponent(topic)}&limit=42`);
  } catch {
    return mockGraph;
  }
}

export async function toggleFavorite(paperId: number, favorite: boolean): Promise<Paper> {
  try {
    return await request<Paper>("/api/library/favorites", {
      method: "POST",
      body: JSON.stringify({ paper_id: paperId, favorite })
    });
  } catch {
    const paper = mockPapers.find((item) => item.id === paperId) ?? mockPapers[0];
    return { ...paper, is_favorite: favorite };
  }
}

export async function addNote(paperId: number, note: string, comment = ""): Promise<Note> {
  return request<Note>("/api/notes", {
    method: "POST",
    body: JSON.stringify({ paper_id: paperId, note, comment })
  });
}

export async function fetchHistory(): Promise<HistoryItem[]> {
  try {
    const data = await request<{ items: HistoryItem[] }>("/api/history?limit=30");
    return data.items;
  } catch {
    return mockHistory;
  }
}
