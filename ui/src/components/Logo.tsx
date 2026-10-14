/** The E-Judgment mark (also the favicon, `app/icon.svg`): E and J sharing one top bar. */
export function LogoMark({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      className={className}
      aria-hidden
      focusable="false"
    >
      <rect width="32" height="32" rx="7" fill="#1d5c45" />
      <g fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="square">
        <path d="M8 8.5H24" />
        <path d="M9.5 8.5V23.5H14.5" />
        <path d="M9.5 16H14" />
        <path d="M21.5 8.5V19.5a4 4 0 0 1-4 4" />
      </g>
    </svg>
  );
}
