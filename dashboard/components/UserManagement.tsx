"use client";

import { useState, useEffect, useCallback } from 'react';
import { Search, UserPlus, Edit, Trash2, X, AlertTriangle } from 'lucide-react';
import { getUsers, createUser, updateUser, deleteUser } from '@/lib/api';

type Role = "admin" | "operator" | "viewer" | "security";

type Status = "Active" | "Inactive";

interface User {
  id: number;
  username: string;
  role: Role;
  status: Status;
  last_active: string;
}

function getInitials(name: string) {
  return name
    .split(/[\s._-]/)
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

function getRoleBadgeColor(role: string) {
  switch (role) {
    case 'admin':
      return 'bg-red-500/20 text-red-400 border-red-500/50 shadow-[0_0_8px_rgba(239,68,68,0.3)]';
    case 'security':
      return 'bg-[#00e5ff]/10 text-[#00e5ff] border-[#00e5ff]/50 shadow-[0_0_8px_rgba(0,229,255,0.2)]';
    case 'viewer':
      return 'bg-zinc-800/50 text-zinc-400 border-zinc-600';
    default:
      return 'bg-zinc-800/50 text-zinc-400 border-zinc-600';
  }
}

export default function UserManagement() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  
  // Modal states
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  
  // Form states
  const [formUsername, setFormUsername] = useState('');
  const [formPassword, setFormPassword] = useState('');
  const [formRole, setFormRole] = useState<Role>('viewer');
  const [formStatus, setFormStatus] = useState<Status>('Active');

  const fetchUsers = useCallback(async () => {
    try {
      const data = await getUsers();
      setUsers(Array.isArray(data) ? data : []);
      setError(null);
    } catch {
      console.error('Failed to fetch users');
      setError('Failed to connect to backend');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const resetForm = () => {
    setFormUsername('');
    setFormPassword('');
    setFormRole('viewer');
    setFormStatus('Active');
  };

  const handleAddUser = async () => {
    if (!formUsername || !formPassword) return;
    setActionLoading(true);
    try {
      await createUser({ username: formUsername, password: formPassword, role: formRole });
      await fetchUsers();
      setError(null);
      setShowAddModal(false);
      resetForm();
    } catch (err) {
      console.error('Failed to create user:', err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(false);
    }
  };

  const handleEditUser = async () => {
    if (!selectedUser) return;
    setActionLoading(true);
    try {
      const updateData: { username?: string; password?: string; role?: Role; status?: Status } = {
        username: formUsername,
        role: formRole,
        status: formStatus,
      };
      if (formPassword) {
        updateData.password = formPassword;
      }
      await updateUser(selectedUser.id, updateData);
      await fetchUsers();
      setError(null);
      setShowEditModal(false);
      setSelectedUser(null);
      resetForm();
    } catch (err) {
      console.error('Failed to update user:', err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeleteUser = async () => {
    if (!selectedUser) return;
    setActionLoading(true);
    try {
      await deleteUser(selectedUser.id);
      await fetchUsers();
      setError(null);
      setShowDeleteModal(false);
      setSelectedUser(null);
    } catch (err) {
      console.error('Failed to delete user:', err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(false);
    }
  };

  const openEditModal = (user: User) => {
    setSelectedUser(user);
    setFormUsername(user.username);
    setFormPassword('');
    setFormRole(user.role);
    setFormStatus(user.status);
    setShowEditModal(true);
  };

  const openDeleteModal = (user: User) => {
    setSelectedUser(user);
    setShowDeleteModal(true);
  };

  const filtered = users.filter(
    (u) =>
      !searchQuery ||
      u.username.toLowerCase().includes(searchQuery.toLowerCase()) ||
      u.role.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex-1 bg-[#0a0a0c] overflow-auto">
      <div className="p-6">
        <div className="mb-6">
          <h1 className="text-[#00e5ff] font-mono text-sm uppercase tracking-widest mb-1">👥 OPERATORS</h1>
          <p className="text-zinc-600 text-xs font-mono">{'// SYSTEM ACCESS CONTROL PANEL'}</p>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="mb-4 bg-yellow-500/10 border border-yellow-500/30 rounded p-3 shadow-[0_0_15px_rgba(234,179,8,0.1)]">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-4 h-4 text-yellow-500 flex-shrink-0" />
              <p className="text-yellow-400 text-xs font-mono uppercase tracking-wider">{error}</p>
            </div>
          </div>
        )}

        <div className="bg-black/40 backdrop-blur-md border border-[#00e5ff]/20 rounded shadow-[0_0_20px_rgba(0,229,255,0.05)]">
          <div className="border-b border-[#00e5ff]/20 p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-[#00e5ff]/70 text-[10px] font-mono uppercase tracking-widest">USER ACCOUNTS</h2>
              <button
                type="button"
                onClick={() => { resetForm(); setShowAddModal(true); }}
                className="flex items-center bg-transparent border border-[#00e5ff]/50 text-[#00e5ff] hover:bg-[#00e5ff]/10 hover:shadow-[0_0_15px_rgba(0,229,255,0.2)] font-mono text-[10px] uppercase tracking-wider px-3 h-8 rounded transition-all"
              >
                <UserPlus className="w-3 h-3 mr-1.5" />
                ➕ ADD OPERATOR
              </button>
            </div>
          </div>
          <div className="p-4">
            <div className="mb-4">
              <div className="relative flex items-center gap-2">
                <label htmlFor="user-search" className="sr-only">Search users</label>
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-3.5 h-3.5 text-[#00e5ff]/50" />
                <input
                  id="user-search"
                  placeholder="🔍 SEARCH OPERATORS..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 bg-black/40 border border-[#00e5ff]/30 text-[#00e5ff] placeholder:text-[#00e5ff]/30 font-mono text-xs h-9 w-full md:w-80 rounded focus:outline-none focus:border-[#00e5ff] focus:shadow-[0_0_10px_rgba(0,229,255,0.2)] transition-all"
                />
              </div>
            </div>

            {loading ? (
              <p className="text-[#00e5ff]/50 text-xs font-mono text-center py-8">{'// LOADING USER DATABASE...'}</p>
            ) : (
              <div className="border border-[#00e5ff]/20 rounded overflow-x-auto">
                <table className="w-full text-left border-collapse min-w-[800px]">
                  <thead>
                    <tr className="border-b border-[#00e5ff]/20 bg-[#00e5ff]/5">
                      <th className="p-3 text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-widest">USER</th>
                      <th className="p-3 text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-widest">ROLE</th>
                      <th className="p-3 text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-widest">STATUS</th>
                      <th className="p-3 text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-widest">LAST ACTIVE</th>
                      <th className="p-3 text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-widest">ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((user) => (
                      <tr
                        key={user.id}
                        className="border-b border-[#00e5ff]/10 hover:bg-[#00e5ff]/5 transition-colors last:border-0"
                      >
                        <td className="p-3">
                          <div className="flex items-center gap-3">
                            <div className="h-8 w-8 bg-[#00e5ff]/10 border border-[#00e5ff]/30 rounded-full flex items-center justify-center shrink-0">
                              <span className="text-[#00e5ff] text-xs font-mono">
                                {getInitials(user.username)}
                              </span>
                            </div>
                            <div>
                              <div className="text-zinc-200 text-sm font-mono">{user.username}</div>
                              <div className="text-[#00e5ff]/50 text-[10px] font-mono">{user.username}@threatsense.io</div>
                            </div>
                          </div>
                        </td>
                        <td className="p-3">
                          <div className={`inline-block px-2 py-0.5 border rounded text-[10px] font-mono uppercase tracking-wider ${getRoleBadgeColor(user.role)}`}>
                            {user.role}
                          </div>
                        </td>
                        <td className="p-3">
                          <div
                            className={`inline-flex items-center gap-1.5 px-2 py-0.5 border rounded text-[10px] font-mono uppercase tracking-wider ${(user.status || '').toString().trim().toLowerCase() === 'active'
                                ? 'bg-green-500/20 text-green-400 border-green-500/50 shadow-[0_0_8px_rgba(34,197,94,0.2)]'
                                : 'bg-zinc-800/50 text-zinc-500 border-zinc-600'
                              }`}
                          >
                            <span className={`w-1.5 h-1.5 rounded-full ${(user.status || '').toString().trim().toLowerCase() === 'active' ? 'bg-green-400 animate-pulse' : 'bg-zinc-500'}`}></span>
                            {user.status}
                          </div>
                        </td>
                        <td className="p-3 text-zinc-500 text-xs font-mono">
                          {user.last_active}
                        </td>
                        <td className="p-3">
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => openEditModal(user)}
                              className="flex items-center justify-center text-[#00e5ff]/50 hover:text-[#00e5ff] hover:bg-[#00e5ff]/10 h-7 w-7 rounded transition-all"
                              aria-label={`Edit ${user.username}`}
                            >
                              <Edit className="w-3.5 h-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => openDeleteModal(user)}
                              className="flex items-center justify-center text-red-500/50 hover:text-red-400 hover:bg-red-500/10 h-7 w-7 rounded transition-all"
                              aria-label={`Delete ${user.username}`}
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={5} className="p-8 text-center text-zinc-600 text-xs font-mono">
                          {'// NO OPERATORS FOUND'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Add User Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#0a0a0c] border border-[#00e5ff]/30 rounded-lg max-w-md w-full shadow-[0_0_30px_rgba(0,229,255,0.2)]">
            <div className="flex items-center justify-between p-4 border-b border-[#00e5ff]/20">
              <h2 className="text-[#00e5ff] font-mono text-sm uppercase tracking-widest">➕ ADD NEW OPERATOR</h2>
              <button onClick={() => setShowAddModal(false)} className="text-zinc-500 hover:text-[#00e5ff] transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-wider block mb-1">USERNAME</label>
                <input
                  type="text"
                  value={formUsername}
                  onChange={(e) => setFormUsername(e.target.value)}
                  placeholder="Enter username"
                  className="w-full bg-black/40 border border-[#00e5ff]/30 text-[#00e5ff] placeholder:text-[#00e5ff]/30 font-mono text-sm h-9 px-3 rounded focus:outline-none focus:border-[#00e5ff] focus:shadow-[0_0_10px_rgba(0,229,255,0.2)] transition-all"
                />
              </div>
              <div>
                <label className="text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-wider block mb-1">PASSWORD</label>
                <input
                  type="password"
                  value={formPassword}
                  onChange={(e) => setFormPassword(e.target.value)}
                  placeholder="Enter password"
                  className="w-full bg-black/40 border border-[#00e5ff]/30 text-[#00e5ff] placeholder:text-[#00e5ff]/30 font-mono text-sm h-9 px-3 rounded focus:outline-none focus:border-[#00e5ff] focus:shadow-[0_0_10px_rgba(0,229,255,0.2)] transition-all"
                />
              </div>
              <div>
                <label className="text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-wider block mb-1">ROLE</label>
                <select
                  value={formRole}
                  onChange={(e) => setFormRole(e.target.value as Role)}
                  className="w-full bg-black/40 border border-[#00e5ff]/30 text-[#00e5ff] font-mono text-sm h-9 px-3 rounded focus:outline-none focus:border-[#00e5ff] appearance-none cursor-pointer"
                >
                  <option value="viewer">VIEWER</option>
                  <option value="security">SECURITY</option>
                  <option value="admin">ADMIN</option>
                </select>
              </div>
            </div>
            <div className="flex items-center gap-2 p-4 border-t border-[#00e5ff]/20">
              <button
                onClick={handleAddUser}
                disabled={actionLoading || !formUsername || !formPassword}
                className="flex items-center gap-1.5 bg-transparent border border-[#00e5ff]/50 text-[#00e5ff] hover:bg-[#00e5ff]/10 hover:shadow-[0_0_15px_rgba(0,229,255,0.2)] font-mono text-[10px] uppercase tracking-wider px-3 h-8 rounded transition-all disabled:opacity-50"
              >
                {actionLoading ? '...' : '✅ CREATE OPERATOR'}
              </button>
              <button
                onClick={() => setShowAddModal(false)}
                className="flex items-center gap-1.5 bg-transparent border border-zinc-600 text-zinc-400 hover:bg-zinc-800/50 font-mono text-[10px] uppercase tracking-wider px-3 h-8 rounded transition-all"
              >
                ✕ CANCEL
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit User Modal */}
      {showEditModal && selectedUser && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#0a0a0c] border border-[#00e5ff]/30 rounded-lg max-w-md w-full shadow-[0_0_30px_rgba(0,229,255,0.2)]">
            <div className="flex items-center justify-between p-4 border-b border-[#00e5ff]/20">
              <h2 className="text-[#00e5ff] font-mono text-sm uppercase tracking-widest">✏️ EDIT OPERATOR</h2>
              <button onClick={() => setShowEditModal(false)} className="text-zinc-500 hover:text-[#00e5ff] transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-wider block mb-1">USERNAME</label>
                <input
                  type="text"
                  value={formUsername}
                  onChange={(e) => setFormUsername(e.target.value)}
                  placeholder="Enter username"
                  className="w-full bg-black/40 border border-[#00e5ff]/30 text-[#00e5ff] placeholder:text-[#00e5ff]/30 font-mono text-sm h-9 px-3 rounded focus:outline-none focus:border-[#00e5ff] focus:shadow-[0_0_10px_rgba(0,229,255,0.2)] transition-all"
                />
              </div>
              <div>
                <label className="text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-wider block mb-1">PASSWORD (LEAVE BLANK TO KEEP)</label>
                <input
                  type="password"
                  value={formPassword}
                  onChange={(e) => setFormPassword(e.target.value)}
                  placeholder="Enter new password"
                  className="w-full bg-black/40 border border-[#00e5ff]/30 text-[#00e5ff] placeholder:text-[#00e5ff]/30 font-mono text-sm h-9 px-3 rounded focus:outline-none focus:border-[#00e5ff] focus:shadow-[0_0_10px_rgba(0,229,255,0.2)] transition-all"
                />
              </div>
              <div>
                <label className="text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-wider block mb-1">ROLE</label>
                <select
                  value={formRole}
                  onChange={(e) => setFormRole(e.target.value as Role)}
                  className="w-full bg-black/40 border border-[#00e5ff]/30 text-[#00e5ff] font-mono text-sm h-9 px-3 rounded focus:outline-none focus:border-[#00e5ff] appearance-none cursor-pointer"
                >
                  <option value="viewer">VIEWER</option>
                  <option value="security">SECURITY</option>
                  <option value="admin">ADMIN</option>
                </select>
              </div>
              <div>
                <label className="text-[#00e5ff]/60 text-[10px] font-mono uppercase tracking-wider block mb-1">STATUS</label>
                <select
                  value={formStatus}
                  onChange={(e) => setFormStatus(e.target.value as Status)}
                  className="w-full bg-black/40 border border-[#00e5ff]/30 text-[#00e5ff] font-mono text-sm h-9 px-3 rounded focus:outline-none focus:border-[#00e5ff] appearance-none cursor-pointer"
                >
                  <option value="Active">ACTIVE</option>
                  <option value="Inactive">INACTIVE</option>
                </select>
              </div>
            </div>
            <div className="flex items-center gap-2 p-4 border-t border-[#00e5ff]/20">
              <button
                onClick={handleEditUser}
                disabled={actionLoading || !formUsername}
                className="flex items-center gap-1.5 bg-transparent border border-[#00e5ff]/50 text-[#00e5ff] hover:bg-[#00e5ff]/10 hover:shadow-[0_0_15px_rgba(0,229,255,0.2)] font-mono text-[10px] uppercase tracking-wider px-3 h-8 rounded transition-all disabled:opacity-50"
              >
                {actionLoading ? '...' : '💾 SAVE CHANGES'}
              </button>
              <button
                onClick={() => setShowEditModal(false)}
                className="flex items-center gap-1.5 bg-transparent border border-zinc-600 text-zinc-400 hover:bg-zinc-800/50 font-mono text-[10px] uppercase tracking-wider px-3 h-8 rounded transition-all"
              >
                ✕ CANCEL
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && selectedUser && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#0a0a0c] border border-red-500/30 rounded-lg max-w-sm w-full shadow-[0_0_30px_rgba(239,68,68,0.2)]">
            <div className="flex items-center justify-between p-4 border-b border-red-500/20">
              <h2 className="text-red-400 font-mono text-sm uppercase tracking-widest">⚠️ CONFIRM PURGE</h2>
              <button onClick={() => setShowDeleteModal(false)} className="text-zinc-500 hover:text-red-400 transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4">
              <p className="text-zinc-300 text-sm font-mono">
                // DEACTIVATE OPERATOR: <span className="text-red-400">{selectedUser.username}</span>?
              </p>
              <p className="text-zinc-600 text-xs font-mono mt-2">// This will set the user status to Inactive.</p>
            </div>
            <div className="flex items-center gap-2 p-4 border-t border-red-500/20">
              <button
                onClick={handleDeleteUser}
                disabled={actionLoading}
                className="flex items-center gap-1.5 bg-transparent border border-red-500/50 text-red-400 hover:bg-red-500/10 hover:shadow-[0_0_15px_rgba(239,68,68,0.2)] font-mono text-[10px] uppercase tracking-wider px-3 h-8 rounded transition-all disabled:opacity-50"
              >
                {actionLoading ? '...' : '🗑️ PURGE OPERATOR'}
              </button>
              <button
                onClick={() => setShowDeleteModal(false)}
                className="flex items-center gap-1.5 bg-transparent border border-zinc-600 text-zinc-400 hover:bg-zinc-800/50 font-mono text-[10px] uppercase tracking-wider px-3 h-8 rounded transition-all"
              >
                ✕ ABORT
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
