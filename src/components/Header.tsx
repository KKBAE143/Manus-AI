import React from 'react';
import { Search, Bell } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

interface HeaderProps {
  title: string;
  subtitle: string;
}

export default function Header({ title, subtitle }: HeaderProps) {
  const { user } = useAuth();

  return (
    <header className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4 px-6 pt-6 md:p-0 shrink-0">
      <div>
        <h1 className="text-3xl md:text-[40px] font-extrabold mb-1 text-[#222222] tracking-tight">{title}</h1>
        <p className="text-sm md:text-base text-[#888888]">{subtitle}</p>
      </div>
      <div className="flex items-center gap-3 w-full md:w-auto mt-2 md:mt-0">
        <div className="hidden md:flex items-center gap-2 bg-green-50 text-green-700 px-3 py-1.5 rounded-full text-xs font-bold border border-green-100">
          <div className="w-2 h-2 bg-green-500 rounded-full"></div>
          Free API
        </div>
        
        <div className="relative flex items-center flex-1 md:flex-none bg-white rounded-full shadow-sm px-4 py-2.5 w-full md:w-64">
          <Search size={16} className="text-gray-400 mr-2 shrink-0" />
          <input
            type="text"
            placeholder="Search..."
            className="bg-transparent border-none focus:outline-none text-sm w-full text-[#222222] placeholder-gray-400"
          />
        </div>
        
        <button className="w-10 h-10 md:w-11 md:h-11 rounded-full bg-white shadow-sm flex items-center justify-center text-gray-500 hover:text-[#222222] transition-colors shrink-0">
          <Bell size={18} />
        </button>
        
        <div className="w-10 h-10 md:w-11 md:h-11 rounded-full bg-[#35433C] text-white flex items-center justify-center font-semibold shadow-sm shrink-0 text-sm">
          {user?.displayName?.charAt(0).toUpperCase() || 'D'}
        </div>
      </div>
    </header>
  );
}
