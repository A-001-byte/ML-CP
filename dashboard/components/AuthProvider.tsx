"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { useRouter, usePathname } from "next/navigation";
import { setApiToken, getMe, logout as apiLogout } from "@/lib/api";

interface AuthState {
  token: string | null;       // in-memory only — never in localStorage
  role: string | null;
  username: string | null;
  isReady: boolean;
  setAuth: (token: string, role: string, username: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState>({
  token: null,
  role: null,
  username: null,
  isReady: false,
  setAuth: () => {},
  logout: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

const PUBLIC_PATHS = ["/login", "/signup"];

export default function AuthProvider({ children }: { children: ReactNode }) {
  const router   = useRouter();
  const pathname = usePathname();

  const [token,    setToken]    = useState<string | null>(null);
  const [role,     setRole]     = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [isReady,  setIsReady]  = useState(false);

  // ── On mount: restore session from HttpOnly cookie ──────────────
  useEffect(() => {
    async function restoreSession() {
      // Optimistic: load display values from localStorage for instant render
      const cachedRole     = localStorage.getItem("role");
      const cachedUsername = localStorage.getItem("username");
      if (cachedRole)     setRole(cachedRole);
      if (cachedUsername) setUsername(cachedUsername);

      // Verify the session is still valid via the HttpOnly cookie
      const me = await getMe();
      if (me) {
        // Session valid — update display state from server response
        setRole(me.role);
        setUsername(me.username);
        localStorage.setItem("role",     me.role);
        localStorage.setItem("username", me.username);
      } else {
        // Cookie expired or invalid — clear everything
        setRole(null);
        setUsername(null);
        setToken(null);
        setApiToken(null);
        localStorage.removeItem("role");
        localStorage.removeItem("username");
      }

      setIsReady(true);
    }

    restoreSession();
  }, []);

  // ── Redirect unauthenticated users ───────────────────────────────
  useEffect(() => {
    if (!isReady) return;
    const isPublic = PUBLIC_PATHS.some((p) => pathname?.startsWith(p));
    const authed   = role !== null;   // role is only set when /me succeeds
    if (!authed && !isPublic) {
      router.replace("/login");
    }
  }, [isReady, role, pathname, router]);

  // ── setAuth: called by LoginScreen after successful login ────────
  const setAuth = useCallback(
    (newToken: string, newRole: string, newUsername: string) => {
      setToken(newToken);
      setRole(newRole);
      setUsername(newUsername);
      setApiToken(newToken);                        // wire into api.ts Bearer fallback
      localStorage.setItem("role",     newRole);    // display cache only
      localStorage.setItem("username", newUsername);
      // NOTE: token intentionally NOT stored in localStorage
    },
    []
  );

  // ── logout ────────────────────────────────────────────────────────
  const logout = useCallback(async () => {
    await apiLogout();          // clears HttpOnly cookie on the backend
    setToken(null);
    setRole(null);
    setUsername(null);
    setApiToken(null);
    localStorage.removeItem("role");
    localStorage.removeItem("username");
    router.replace("/login");
  }, [router]);

  if (!isReady) return null;

  return (
    <AuthContext.Provider value={{ token, role, username, isReady, setAuth, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
