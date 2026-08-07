import type { ReactNode } from "react"
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  CircleDashedIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { cn } from "@/lib/utils"

export const MINIMUM_CHALLENGE_AMOUNT = 5

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.replaceAll("_", " ").toUpperCase()
  const neutral = normalized.includes("NO APPROVED") || normalized === "LOCKED"
  const success = [
    "PASS",
    "MATCH",
    "WITHIN",
    "ADMITTED",
    "APPROVED",
    "ACTIVE",
    "COMPLETE",
    "CONNECTED",
    "REVIEWED",
    "READY",
    "UPLOADED",
    "UNLOCKED",
  ].some((value) => normalized.includes(value))
  const destructive = ["CHALLENGE", "DENIED", "FAILED"].some((value) =>
    normalized.includes(value)
  )
  const warning = [
    "PENDING",
    "PROVISIONAL",
    "REVIEW",
    "BELOW GATE",
    "RESEARCH",
    "SPLIT LIABILITY",
  ].some((value) => normalized.includes(value))

  return (
    <Badge
      variant={
        neutral
          ? "outline"
          : success
            ? "success"
            : destructive
              ? "destructive"
              : warning
                ? "warning"
                : "outline"
      }
    >
      {normalized}
    </Badge>
  )
}

export function ConfidenceCell({ value }: { value?: number }) {
  if (value === undefined)
    return <span className="text-muted-foreground">—</span>
  if (value > 95)
    return (
      <span
        className="inline-flex items-center gap-1 font-medium text-success"
        title={`${value}% confidence · automatically approved`}
      >
        <CheckCircle2Icon className="size-4" aria-hidden />
        Approved
      </span>
    )
  return <span className="font-medium tabular-nums">{value}%</span>
}

export function ScreenHeading({
  title,
  description,
  action,
  compact = false,
}: {
  title: string
  description: string
  action?: ReactNode
  compact?: boolean
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4",
        compact
          ? "xl:flex-col"
          : "xl:flex-row xl:items-start xl:justify-between"
      )}
    >
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          {description}
        </p>
      </div>
      {action ? (
        <div
          className={cn(
            "flex flex-wrap items-center gap-2",
            !compact && "xl:shrink-0"
          )}
        >
          {action}
        </div>
      ) : null}
    </div>
  )
}

export function DataCard({
  title,
  description,
  action,
  children,
  className,
}: {
  title: string
  description?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <Card className={cn("min-w-0", className)}>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <CardTitle>{title}</CardTitle>
            {description ? (
              <CardDescription>{description}</CardDescription>
            ) : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export function Metric({
  label,
  value,
  hint,
  emphasis = false,
}: {
  label: string
  value: string
  hint?: string
  emphasis?: boolean
}) {
  return (
    <div className="min-w-0 px-1 py-1">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 truncate text-xl font-semibold tracking-tight tabular-nums",
          emphasis && "text-destructive"
        )}
      >
        {value}
      </p>
      {hint ? (
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}

export function CheckIcon({
  status,
}: {
  status: "pass" | "review" | "pending"
}) {
  if (status === "pass")
    return <CheckCircle2Icon className="size-4 text-success" aria-hidden />
  if (status === "review")
    return <AlertCircleIcon className="size-4 text-warning" aria-hidden />
  return (
    <CircleDashedIcon className="size-4 text-muted-foreground" aria-hidden />
  )
}
