import type { ReactNode } from "react";

// Outline icons drawn on a 24px grid. They are decorative: every use sits
// beside a visible or accessible text label.
const PATHS: Record<string, ReactNode> = {
  library: (
    <>
      <path d="M4 19.5V5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v14.5" />
      <path d="M9 19.5V7a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v12.5" />
      <path d="m14.6 7.4 2.9-.8a1 1 0 0 1 1.2.7l3 11.2" />
      <path d="M3 20h18" />
    </>
  ),
  updates: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18Z" />
    </>
  ),
  review: (
    <>
      <path d="M12 3.5 14.2 9l5.8.4-4.5 3.7 1.5 5.7L12 15.6l-5 3.2 1.5-5.7L4 9.4 9.8 9Z" />
    </>
  ),
  activity: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  settings: (
    <>
      <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="10" cy="17" r="2" />
    </>
  ),
  system: (
    <>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </>
  ),
  light: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  dark: <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />,
  "sign-out": (
    <>
      <path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" />
      <path d="M10 16l-4-4 4-4M6 12h10" />
    </>
  ),
};

export default function Icon({
  name,
  size = 20,
}: {
  name: string;
  size?: number;
}) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}

export function BrandMark({ size = 30 }: { size?: number }) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      <rect width="32" height="32" rx="9" fill="var(--accent)" />
      <path
        d="M8 9.5c2.8-.9 5.5-.6 8 1v13c-2.5-1.6-5.2-1.9-8-1Z"
        fill="var(--accent-contrast)"
        opacity="0.9"
      />
      <path
        d="M24 9.5c-2.8-.9-5.5-.6-8 1v13c2.5-1.6 5.2-1.9 8-1Z"
        fill="var(--accent-contrast)"
        opacity="0.65"
      />
    </svg>
  );
}
