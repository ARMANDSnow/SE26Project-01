import type { Paper } from "@/types"

export const sectionNames: Record<string, string> = {
  summary: "摘要",
  concepts: "概念",
  methods: "方法",
  experiments: "实验",
}

export const defaultCategories = ["cs.AI", "cs.CL", "cs.LG", "cs.IR"]

export function statusText(status: Paper["processing_status"]) {
  return status === "processed" ? "已解析" : status === "pending" ? "待处理" : "失败"
}

export function uniqueValues(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)))
}

export function truncateLabel(value: string, limit = 18) {
  return value.length > limit ? `${value.slice(0, limit)}...` : value
}

export function plainSnippet(content: string, limit = 150) {
  return content
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
    .map((line) => line.replace(/^- /, ""))
    .join(" ")
    .slice(0, limit)
}
