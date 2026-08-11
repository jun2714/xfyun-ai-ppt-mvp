type IconProps = {
  className?: string | undefined;
};

function IconBase({ children, className }: IconProps & { children: React.ReactNode }) {
  return <svg
    aria-hidden="true"
    className={className}
    fill="none"
    height="18"
    viewBox="0 0 24 24"
    width="18"
    xmlns="http://www.w3.org/2000/svg"
  >
    {children}
  </svg>;
}

export function ArrowRightIcon({ className }: IconProps) {
  return <IconBase className={className}>
    <path d="M5 12h14M14 7l5 5-5 5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
  </IconBase>;
}

export function ArrowLeftIcon({ className }: IconProps) {
  return <IconBase className={className}>
    <path d="M19 12H5m5-5-5 5 5 5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
  </IconBase>;
}

export function PlusIcon({ className }: IconProps) {
  return <IconBase className={className}>
    <path d="M12 5v14M5 12h14" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
  </IconBase>;
}

export function SparklesIcon({ className }: IconProps) {
  return <IconBase className={className}>
    <path d="M9.5 3.5c.55 3.05 1.95 4.45 5 5-3.05.55-4.45 1.95-5 5-.55-3.05-1.95-4.45-5-5 3.05-.55 4.45-1.95 5-5Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.7" />
    <path d="M17.5 13.5c.33 1.83 1.17 2.67 3 3-1.83.33-2.67 1.17-3 3-.33-1.83-1.17-2.67-3-3 1.83-.33 2.67-1.17 3-3Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.7" />
  </IconBase>;
}

export function MoreVerticalIcon({ className }: IconProps) {
  return <IconBase className={className}>
    <circle cx="12" cy="5" fill="currentColor" r="1.5" />
    <circle cx="12" cy="12" fill="currentColor" r="1.5" />
    <circle cx="12" cy="19" fill="currentColor" r="1.5" />
  </IconBase>;
}

export function CopyIcon({ className }: IconProps) {
  return <IconBase className={className}>
    <rect height="11" rx="1.5" stroke="currentColor" strokeWidth="1.7" width="11" x="8" y="8" />
    <path d="M16 8V6.5A1.5 1.5 0 0 0 14.5 5h-8A1.5 1.5 0 0 0 5 6.5v8A1.5 1.5 0 0 0 6.5 16H8" stroke="currentColor" strokeLinecap="round" strokeWidth="1.7" />
  </IconBase>;
}

export function TrashIcon({ className }: IconProps) {
  return <IconBase className={className}>
    <path d="M5 7h14M9 7V4.8h6V7m2 0-.7 12H7.7L7 7m3 3v6m4-6v6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
  </IconBase>;
}
