import React from 'react'
import { Badge as ShadcnBadge, badgeVariants } from './ui/badge'
import {
  Table as ShadcnTable,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from './ui/table'

export { Button } from './ui/button'
export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent } from './ui/card'
export { Input } from './ui/input'
export { Label } from './ui/label'
export { Switch } from './ui/switch'
export { Select } from './ui/select'
export { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs'
export { Separator } from './ui/separator'
export { ShadcnBadge, badgeVariants }

export const Table = ({ cols, rows }) => (
  <ShadcnTable>
    <TableHeader>
      <TableRow>
        {cols.map((c, i) => <TableHead key={i} className={typeof c === 'object' && c.align ? `text-${c.align}` : ''}>{typeof c === 'string' ? c : c.label}</TableHead>)}
      </TableRow>
    </TableHeader>
    <TableBody>
      {rows.map((r, i) => (
        <TableRow key={i}>
          {r.map((c, j) => <TableCell key={j} className={typeof cols[j] === 'object' && cols[j].align ? `text-${cols[j].align}` : ''}>{c}</TableCell>)}
        </TableRow>
      ))}
    </TableBody>
  </ShadcnTable>
)

export { TableBody, TableCell, TableHead, TableHeader, TableRow, ShadcnTable }

const dirFor = (dir) => {
  if (['bullish', 'up', 'long', 'trending_up', 'ok'].includes(dir)) return 'success'
  if (['bearish', 'down', 'short', 'trending_down', 'crash', 'failing', 'halted'].includes(dir)) return 'destructive'
  return 'secondary'
}

export const Badge = ({ dir, children }) => {
  const variant = dirFor(dir)
  return <ShadcnBadge variant={variant}>{children ?? dir}</ShadcnBadge>
}

export const Tile = ({ k, v }) => (
  <div className="rounded-lg border border-border bg-card p-4 shadow-sm transition-all hover:shadow-md min-w-[140px]">
    <div className="text-xs text-muted-foreground">{k}</div>
    <div className="text-2xl font-bold">{v}</div>
  </div>
)

export const Gauge = ({ value }) => {
  const pct = Math.max(0, Math.min(1, value)) * 100
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted/30">
      <div
        className="h-full rounded-full bg-primary transition-all duration-500"
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

export const Empty = ({ what }) => (
  <p className="text-sm text-muted-foreground">no {what} yet — start the paper loop to populate the journal.</p>
)

export const Spark = ({ points, w = 600, h = 120, color = 'hsl(var(--primary))' }) => {
  if (!points || points.length < 2) return <p className="text-sm text-muted-foreground">no series</p>
  const min = Math.min(...points)
  const max = Math.max(...points)
  const rng = max - min || 1
  const path = points.map((p, i) => `${(i / (points.length - 1)) * w},${h - ((p - min) / rng) * h}`).join(' ')
  return (
    <svg width={w} height={h} className="rounded-lg bg-card">
      <polyline fill="none" stroke={color} strokeWidth="2" points={path} />
    </svg>
  )
}
