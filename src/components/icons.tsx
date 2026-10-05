import type { SVGProps } from "react";

/**
 * 统一图标集（Lucide/Heroicons 风格，24×24，currentColor）。
 * 替代原项目中用 emoji 当图标的反模式。颜色随 currentColor 继承文字色。
 */

type IconProps = SVGProps<SVGSVGElement>;

function Base({ children, ...props }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

/** 海龟汤 Logo（龟 + 汤碗意象） */
export function TurtleIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 15c0-4 3.6-7 8-7s8 3 8 7" />
      <path d="M4 15h16" />
      <circle cx="18.6" cy="11" r="1.6" />
      <path d="M12 8v7M8 11h8" />
      <path d="M7 18.5l-1.4 2M12 19v2.6M17 18.5l1.4 2" />
    </Base>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.35-4.35" />
    </Base>
  );
}

export function ArrowLeftIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M15 19l-7-7 7-7" />
    </Base>
  );
}

export function ArrowRightIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M9 5l7 7-7 7" />
    </Base>
  );
}

export function GiftIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="3" y="8" width="18" height="13" rx="1.5" />
      <path d="M12 8v13M3 12h18" />
      <path d="M12 8C12 8 10 3 7.5 4.5S8 8 12 8zM12 8c0 0 2-5 4.5-3.5S16 8 12 8z" />
    </Base>
  );
}

export function CoffeeIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 9h13v5a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4V9z" />
      <path d="M17 10h2.5a2.5 2.5 0 0 1 0 5H17" />
      <path d="M8 3v2M12 3v2M16 3v2" />
    </Base>
  );
}

/** 主持人头像（面具） */
export function MaskIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M3 8c0-2 4-4 9-4s9 2 9 4c0 5-4 11-9 11S3 13 3 8z" />
      <path d="M9 9.5h.01M15 9.5h.01" />
      <path d="M8.5 14c1.5 1.2 5.5 1.2 7 0" />
    </Base>
  );
}

export function RefreshIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M21 12a9 9 0 1 1-3-6.7" />
      <path d="M21 4v4h-4" />
    </Base>
  );
}

export function FlagIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M5 21V4M5 4h11l-2 4 2 4H5" />
    </Base>
  );
}

export function TargetIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4.5" />
      <circle cx="12" cy="12" r="0.8" fill="currentColor" />
    </Base>
  );
}

export function TrophyIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M7 4h10v4a5 5 0 0 1-10 0V4z" />
      <path d="M7 5H4v2a3 3 0 0 0 3 3M17 5h3v2a3 3 0 0 1-3 3" />
      <path d="M12 13v3M9 20h6M10 16h4l-.5 4h-3z" />
    </Base>
  );
}

export function LockIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="4.5" y="10" width="15" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
      <path d="M12 14v3" />
    </Base>
  );
}

export function ClipboardIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="5" y="4" width="14" height="17" rx="2" />
      <path d="M9 4a3 3 0 0 1 6 0v1H9V4z" />
      <path d="M9 11h6M9 15h6" />
    </Base>
  );
}

export function ScrollIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M6 4h11a2 2 0 0 1 2 2v12a2 2 0 0 0 2 2H8a2 2 0 0 1-2-2V4z" />
      <path d="M6 4a2 2 0 0 0-2 2v2h2M9 9h7M9 13h7M9 17h4" />
    </Base>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Base>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M5 12.5l4.5 4.5L19 7" />
    </Base>
  );
}

export function AlertIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 3l9 16H3l9-16z" />
      <path d="M12 10v4M12 17h.01" />
    </Base>
  );
}

export function SparkleIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 3l1.8 4.7L18.5 9.5 13.8 11.3 12 16l-1.8-4.7L5.5 9.5l4.7-1.8L12 3z" />
      <path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14z" />
    </Base>
  );
}
