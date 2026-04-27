"use client";

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { login } from '@/lib/api';
import { useAuth } from '@/components/AuthProvider';
import { Shield } from 'lucide-react';

export default function LoginScreen() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const { setAuth } = useAuth();

  const handleSubmit = async (e: React.SyntheticEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const result = await login(username, password);

      if ('token' in result) {
        // Store token in-memory via AuthProvider (NOT in localStorage)
        // HttpOnly cookie is set by the backend on this request
        setAuth(result.token, result.role, result.username ?? username);
        router.push('/monitor');
      } else {
        setError((result as { error: string }).error || 'Invalid credentials');
      }
    } catch {
      setError('Unable to connect to server');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--bg-primary)' }}>
      {/* Subtle background pattern */}
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: `radial-gradient(circle at 1px 1px, rgba(255,255,255,0.15) 1px, transparent 0)`,
          backgroundSize: '32px 32px',
        }}
      />

      <div className="relative w-full max-w-[380px] mx-4">
        {/* Login Card */}
        <div className="panel">
          <div className="p-8">
            {/* Brand */}
            <div className="text-center mb-8">
              <div className="w-12 h-12 rounded-lg mx-auto mb-4 flex items-center justify-center" style={{ background: 'var(--accent-dim)', border: '1px solid rgba(59, 130, 246, 0.2)' }}>
                <Shield className="w-6 h-6" style={{ color: 'var(--accent)' }} />
              </div>
              <h1 className="text-lg font-semibold tracking-wide" style={{ color: 'var(--text-primary)' }}>
                ThreatSense AI
              </h1>
              <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                Surveillance Control Platform
              </p>
            </div>

            {/* Error */}
            {error && (
              <div className="mb-5 p-3 rounded-md text-sm animate-fade-in" style={{ background: 'var(--danger-dim)', border: '1px solid var(--danger-border)', color: 'var(--danger)' }}>
                {error}
              </div>
            )}

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="username" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                  Username
                </label>
                <input
                  id="username"
                  type="text"
                  autoComplete="username"
                  placeholder="Enter username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-md text-sm transition-colors focus:outline-none"
                  style={{
                    background: 'var(--bg-primary)',
                    border: '1px solid var(--border-strong)',
                    color: 'var(--text-primary)',
                  }}
                  onFocus={(e) => { e.target.style.borderColor = 'var(--accent)'; }}
                  onBlur={(e) => { e.target.style.borderColor = 'var(--border-strong)'; }}
                  required
                />
              </div>

              <div>
                <label htmlFor="password" className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>
                  Password
                </label>
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  placeholder="Enter password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-md text-sm transition-colors focus:outline-none"
                  style={{
                    background: 'var(--bg-primary)',
                    border: '1px solid var(--border-strong)',
                    color: 'var(--text-primary)',
                  }}
                  onFocus={(e) => { e.target.style.borderColor = 'var(--accent)'; }}
                  onBlur={(e) => { e.target.style.borderColor = 'var(--border-strong)'; }}
                  required
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="btn-primary w-full py-2.5 rounded-md text-sm font-medium transition-all disabled:opacity-50"
                style={{
                  background: 'var(--accent)',
                  border: 'none',
                  color: 'white',
                  cursor: loading ? 'not-allowed' : 'pointer',
                }}
              >
                {loading ? 'Signing in...' : 'Sign In'}
              </button>
            </form>
          </div>

          {/* Footer */}
          <div className="px-8 py-3" style={{ borderTop: '1px solid var(--border)', background: 'rgba(255,255,255,0.01)' }}>
            <p className="text-center text-[10px]" style={{ color: 'var(--text-dim)' }}>
              Authorized personnel only
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}