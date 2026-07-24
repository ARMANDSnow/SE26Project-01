import type { ResearchRunStatus } from "@/types"
import type { ResearchStepStatus } from "@/types"

export const researchStatusLabel: Record<ResearchRunStatus, string> = {
  queued: "等待执行",
  running: "执行中",
  waiting_input: "等待确认",
  paused: "已暂停",
  completed: "已完成",
  failed: "失败",
  cancelling: "正在停止",
  cancelled: "已取消",
}

export const researchStatusTone: Record<
  ResearchRunStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  queued: "secondary",
  running: "default",
  waiting_input: "outline",
  paused: "outline",
  completed: "secondary",
  failed: "destructive",
  cancelling: "outline",
  cancelled: "outline",
}

export const researchStepStatusLabel: Record<ResearchStepStatus, string> = {
  queued: "等待执行",
  running: "执行中",
  waiting_input: "等待确认",
  paused: "已暂停",
  completed: "已完成",
  failed: "失败",
  skipped: "已跳过",
  cancelled: "已取消",
}
