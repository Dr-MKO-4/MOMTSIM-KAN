import { useState, useCallback, type ReactNode } from "react";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";

interface Props {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export default function Layout({ title, subtitle, children }: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const openSidebar  = useCallback(() => setSidebarOpen(true),  []);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  return (
    <div className="flex min-h-screen bg-bg-primary text-text-primary">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/50 lg:hidden"
          onClick={closeSidebar}
          aria-hidden="true"
        />
      )}

      <Sidebar open={sidebarOpen} onClose={closeSidebar} />

      <div className="flex-1 flex flex-col min-w-0">
        <TopBar title={title} subtitle={subtitle} onMenuClick={openSidebar} />
        <main className="flex-1 p-5 lg:p-6 overflow-y-auto animate-fade-in">
          {children}
        </main>
      </div>
    </div>
  );
}
