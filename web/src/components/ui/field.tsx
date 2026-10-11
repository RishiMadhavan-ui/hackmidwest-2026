import type { ComponentProps, ReactNode } from "react";
import { cn } from "cn";

export const inputClassName = cn(
  "h-10 w-full rounded-lg border border-input bg-card px-3 text-sm text-foreground transition-colors outline-none",
  "placeholder:text-muted-foreground/70",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25",
  "aria-invalid:border-destructive disabled:opacity-60",
);

export function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
  className,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  htmlFor: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(inputClassName, className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(inputClassName, "h-auto min-h-20 py-2 leading-relaxed", className)}
      {...props}
    />
  );
}
