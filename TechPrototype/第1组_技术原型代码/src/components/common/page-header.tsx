import type { ReactNode } from "react"

type PageHeaderProps = {
  eyebrow: string
  title: string
  description?: string
  actions?: ReactNode
}

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0 space-y-2">
        <p className="text-xs font-semibold uppercase text-primary">{eyebrow}</p>
        <h1 className="max-w-4xl text-3xl font-semibold tracking-normal text-foreground md:text-4xl">
          {title}
        </h1>
        {description ? (
          <p className="max-w-3xl text-base leading-7 text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  )
}
