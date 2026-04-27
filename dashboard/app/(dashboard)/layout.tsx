import Sidebar from "@/components/Sidebar";
import AuthProvider from "@/components/AuthProvider";
import { Header } from "@/components/Header";

export default function DashboardLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <AuthProvider>
            <div className="flex h-screen w-full">
                <Sidebar className="w-64 flex-shrink-0 border-r" />
                <div className="flex flex-col flex-1 min-w-0 bg-black">
                    <Header />
                    <main className="flex-1 overflow-auto">{children}</main>
                </div>
            </div>
        </AuthProvider>
    );
}
