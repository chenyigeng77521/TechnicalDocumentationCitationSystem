import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "智能知识库问答",
  description: "基于企业知识库的 AI 智能检索与问答系统",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
