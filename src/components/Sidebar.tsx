import React, { useState } from 'react';
import { NavLink, useMatch, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import {
  LayoutGrid,
  FileText,
  LogOut,
  Layers,
  FileUp,
  BookOpen,
  ClipboardCheck,
  Library,
  Wrench,
} from 'lucide-react';

export default function Sidebar() {
  const [expanded, setExpanded] = useState(false);
  const { user, logOut } = useAuth();
  const navigate = useNavigate();

  const onWorkspaceBase = useMatch('/workspace');
  const onWorkspaceDoc = useMatch('/workspace/:id');
  const onWorkspacePreview = useMatch('/workspace/:id/book-preview');
  const onWorkspace = onWorkspaceBase || onWorkspaceDoc || onWorkspacePreview;

  const onAssemblyBase = useMatch('/assembly');
  const onAssemblyDoc = useMatch('/assembly/:id');
  const onAssembly = onAssemblyBase || onAssemblyDoc;

  const onPublishingBase = useMatch('/publishing');
  const onPublishingDoc = useMatch('/publishing/:id');
  const onPublishing = onPublishingBase || onPublishingDoc;

  const navItems = [
    { icon: LayoutGrid, path: '/', label: 'Dashboard', end: true },
    { icon: FileUp, path: '/upload', label: 'Upload', end: true },
    { icon: FileText, path: '/documents', label: 'My Projects', end: false },
    { icon: ClipboardCheck, path: '/review', label: 'Review', end: true },
  ];

  const customNavItems = [
    { icon: BookOpen, label: 'Workspace', active: !!onWorkspace, onClick: () => navigate('/workspace') },
    { icon: Library, label: 'Assembly', active: !!onAssembly, onClick: () => navigate('/assembly') },
    { icon: Wrench, label: 'Publishing', active: !!onPublishing, onClick: () => navigate('/publishing') },
  ];

  const initials = user?.displayName
    ?.split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2) || 'U';

  const btnBase = `flex items-center rounded-2xl transition-all duration-200 overflow-hidden whitespace-nowrap`;
  const iconWrap = `w-10 h-10 flex items-center justify-center shrink-0`;

  return (
    <>
      {/* Desktop Sidebar */}
      <aside
        onMouseEnter={() => setExpanded(true)}
        onMouseLeave={() => setExpanded(false)}
        className={`hidden md:flex flex-col py-5 px-2 bg-white shadow-sm rounded-[32px] justify-between shrink-0 h-[calc(100vh-48px)] sticky top-6 transition-all duration-300 overflow-hidden ${
          expanded ? 'w-56' : 'w-[72px]'
        }`}
      >
        {/* Top: logo + nav */}
        <div className="flex flex-col gap-6">
          {/* Logo */}
          <div className={`flex items-center px-1 ${expanded ? 'gap-3' : 'justify-center'}`}>
            <div className="w-10 h-10 rounded-full bg-[#6A8776] text-white flex items-center justify-center shrink-0 shadow-sm">
              <Layers size={18} />
            </div>
            {expanded && (
              <span className="font-bold text-[#222] text-sm leading-tight">
                Manuscript<br />
                <span className="text-[#6A8776]">AI</span>
              </span>
            )}
          </div>

          {/* Nav links */}
          <nav className="flex flex-col gap-1">
            {navItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.end}
                className={({ isActive }) =>
                  `${btnBase} ${expanded ? 'gap-3 px-2 py-2' : 'justify-center py-2'} ${
                    isActive
                      ? 'bg-[#222] text-white'
                      : 'text-[#888] hover:bg-gray-100 hover:text-[#333]'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <div className={iconWrap}>
                      <item.icon size={20} />
                    </div>
                    {expanded && (
                      <span className="text-sm font-medium">{item.label}</span>
                    )}
                  </>
                )}
              </NavLink>
            ))}

            <div className="h-px bg-gray-100 my-2 mx-2" />

            {customNavItems.map((item) => (
              <button
                key={item.label}
                onClick={item.onClick}
                className={`${btnBase} ${expanded ? 'gap-3 px-2 py-2' : 'justify-center py-2'} ${
                  item.active
                    ? 'bg-[#222] text-white'
                    : 'text-[#888] hover:bg-gray-100 hover:text-[#333]'
                }`}
              >
                <div className={iconWrap}>
                  <item.icon size={20} />
                </div>
                {expanded && <span className="text-sm font-medium">{item.label}</span>}
              </button>
            ))}
          </nav>
        </div>

        {/* Bottom: sign out + profile */}
        <div className="flex flex-col gap-1">
          <button
            onClick={logOut}
            className={`${btnBase} ${expanded ? 'gap-3 px-2 py-2' : 'justify-center py-2'} text-[#888] hover:bg-gray-100 hover:text-[#333]`}
          >
            <div className={iconWrap}>
              <LogOut size={18} />
            </div>
            {expanded && <span className="text-sm font-medium">Sign Out</span>}
          </button>

          <div className={`flex items-center rounded-2xl px-2 py-2 ${expanded ? 'gap-3' : 'justify-center'}`}>
            <div className="w-10 h-10 rounded-full bg-[#35433C] text-white flex items-center justify-center font-semibold text-sm shrink-0 select-none">
              {initials}
            </div>
            {expanded && (
              <div className="min-w-0">
                <p className="text-xs font-semibold text-[#222] truncate leading-tight">{user?.displayName || 'Local User'}</p>
                <p className="text-[10px] text-[#888] truncate">{user?.email || ''}</p>
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* Mobile Bottom Nav */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 h-[72px] bg-white border-t border-gray-100 flex justify-around items-center px-1 z-50 shadow-[0_-4px_20px_rgba(0,0,0,0.05)]">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.end}
            className={({ isActive }) =>
              `flex flex-col items-center justify-center w-14 h-14 rounded-xl transition-all duration-200 ${
                isActive ? 'text-[#222]' : 'text-[#aaa] hover:text-[#222]'
              }`
            }
          >
            <item.icon size={22} className="mb-0.5" />
            <span className="text-[9px] font-medium">{item.label}</span>
          </NavLink>
        ))}
        {customNavItems.slice(0, 1).map((item) => (
          <button
            key={item.label}
            onClick={item.onClick}
            className={`flex flex-col items-center justify-center w-14 h-14 rounded-xl transition-all duration-200 ${
              item.active ? 'text-[#222]' : 'text-[#aaa] hover:text-[#222]'
            }`}
          >
            <item.icon size={22} className="mb-0.5" />
            <span className="text-[9px] font-medium">{item.label}</span>
          </button>
        ))}
        <button
          onClick={logOut}
          className="flex flex-col items-center justify-center w-14 h-14 rounded-xl text-[#aaa] hover:text-[#222] transition-all"
        >
          <LogOut size={22} className="mb-0.5" />
          <span className="text-[9px] font-medium">Logout</span>
        </button>
      </nav>
    </>
  );
}
