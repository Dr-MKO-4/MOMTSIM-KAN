import type { ReactNode } from "react";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";

interface Props {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export default function Layout({ title, subtitle, children }: Props) {
  return (
    <div className="flex min-h-screen bg-bg-primary text-text-primary">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar title={title} subtitle={subtitle} />
        <main className="flex-1 p-6 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
