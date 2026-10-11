import type { ReactNode } from "react";

export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="flex flex-1 items-start justify-center px-4 py-16 sm:items-center">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1.5 text-sm text-muted-foreground text-pretty">{description}</p>
        <div className="mt-6 rounded-lg border border-border bg-card p-5">{children}</div>
        <p className="mt-4 text-center text-sm text-muted-foreground">{footer}</p>
      </div>
    </div>
  );
}
