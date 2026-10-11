import type { ComponentProps } from "react";
import { cn } from "cn";

import type { Tone } from "@/lib/events";

const TONES: Record<Tone | "outline", string> = {
  neutral: "bg-secondary text-secondary-foreground",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
  outline: "border border-border text-muted-foreground",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: ComponentProps<"span"> & { tone?: Tone | "outline" }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium whitespace-nowrap",
        TONES[tone],
        className,
      )}
      {...props}
    />
  );
}

/** Small colored dot; always paired with a text label, never color alone. */
export function Dot({ tone, className }: { tone: Tone; className?: string }) {
  const colors: Record<Tone, string> = {
    neutral: "bg-muted-foreground/50",
    success: "bg-success",
    warning: "bg-warning",
    danger: "bg-danger",
    info: "bg-info",
  };
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2 shrink-0 rounded-full", colors[tone], className)}
    />
  );
}
