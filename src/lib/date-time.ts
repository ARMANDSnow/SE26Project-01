function parseServerDate(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return null
  const normalized = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(trimmed)
    ? `${trimmed.replace(" ", "T")}Z`
    : trimmed
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatLocalDateTime(value: string) {
  const date = parseServerDate(value)
  if (!date) return value
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date)
}
