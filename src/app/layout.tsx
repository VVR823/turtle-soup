import type { Metadata, Viewport } from "next";
import "@/app/globals.css";
import SiteGate from "@/components/SiteGate";
import FeedbackButton from "@/components/FeedbackButton";

export const metadata: Metadata = {
  title: "许二木海龟汤自助 · AI 主持的海龟汤推理游戏",
  description: "选择一道你感兴趣的汤，用提问来推理真相吧！",
};

// 禁止手机端缩放/双击放大，固定页面尺寸，避免输入框聚焦后无法自动还原
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full overflow-x-hidden">
      <body className="min-h-full flex flex-col overflow-x-hidden bg-canvas text-fg font-sans">
        <SiteGate>
          {children}
          <FeedbackButton />
        </SiteGate>
      </body>
    </html>
  );
}
