import Link from "next/link";

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link
      href={href}
      className="flex items-center gap-2 rounded-md text-[0.95rem] font-semibold tracking-tight outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
    >
      <svg viewBox="0 0 20 20" className="size-5 text-primary" aria-hidden>
        <rect width="20" height="20" rx="5" fill="currentColor" />
        <circle cx="7" cy="13" r="2.6" fill="none" stroke="var(--primary-foreground)" strokeWidth="1.8" />
        <path d="M9 11 L14.5 5.5" stroke="var(--primary-foreground)" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      Leash
    </Link>
  );
}
