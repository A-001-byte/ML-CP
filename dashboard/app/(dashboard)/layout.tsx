"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import Sidebar from "@/components/Sidebar";
import AuthProvider from "@/components/AuthProvider";
import { Header } from "@/components/Header";

export default function DashboardLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const [isMobile, setIsMobile] = useState(false);
    const pathname = usePathname();

    useEffect(() => {
        const check = () => setIsMobile(window.innerWidth < 768);
        check();
        window.addEventListener("resize", check);
        return () => window.removeEventListener("resize", check);
    }, []);

    // Close sidebar on route change (mobile) or when switching to desktop
    useEffect(() => {
        if (isMobile) {
            setSidebarOpen(false);
        }
    }, [pathname, isMobile]);

    return (
        <AuthProvider>
            <div className="dashboard-shell flex h-screen w-full">
                {/* Mobile backdrop */}
                {isMobile && sidebarOpen && (
                    <div
                        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
                        onClick={() => setSidebarOpen(false)}
                    />
                )}

                {/* Single sidebar — static on desktop, overlay on mobile */}
                <div
                    className={
                        isMobile
                            ? `fixed top-0 left-0 z-50 h-screen w-64 transition-transform duration-250 ease-in-out ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}`
                            : "w-64 flex-shrink-0"
                    }
                >
                    {isMobile && sidebarOpen && (
                        <button
                            className="absolute top-3 right-3 z-10 flex items-center justify-center w-8 h-8 rounded-md"
                            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}
                            onClick={() => setSidebarOpen(false)}
                            aria-label="Close menu"
                        >
                            <X className="w-4 h-4" />
                        </button>
                    )}
                    <Sidebar className="w-full h-full border-r" />
                </div>

                <div className="flex flex-col flex-1 min-w-0 bg-black">
                    <div className="flex items-center">
                        {/* Hamburger — only on mobile */}
                        {isMobile && (
                            <button
                                className="ml-3 flex items-center justify-center w-9 h-9 rounded-md"
                                style={{ border: "1px solid var(--border)", background: "var(--bg-panel)", color: "var(--text-secondary)" }}
                                onClick={() => setSidebarOpen(true)}
                                aria-label="Open menu"
                            >
                                <Menu className="w-4 h-4" />
                            </button>
                        )}
                        <div className="flex-1">
                            <Header />
                        </div>
                    </div>
                    <main className="flex-1 overflow-auto">{children}</main>
                </div>
            </div>
        </AuthProvider>
    );
}
