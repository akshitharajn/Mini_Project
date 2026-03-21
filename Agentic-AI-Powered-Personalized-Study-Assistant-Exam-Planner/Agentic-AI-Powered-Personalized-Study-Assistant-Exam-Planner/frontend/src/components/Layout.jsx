import React from 'react';
import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { useUser } from '../context/UserContext';
import {
  LayoutDashboard,
  User,
  BookOpen,
  CalendarDays,
  BarChart3,
  FileQuestion,
  MessageSquare,
  Share2,
  LogOut,
  Sparkles,
  Sun,
  Moon,
  Monitor,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';

const NAV = [
  { to: '/', label: 'Home', icon: Sparkles },
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/subjects', label: 'Subjects', icon: BookOpen },
  { to: '/schedule', label: 'Schedule', icon: CalendarDays },
  { to: '/progress', label: 'Progress', icon: BarChart3 },
  { to: '/quiz', label: 'Quiz', icon: FileQuestion },
  { to: '/mind-map', label: 'Mind Map', icon: Share2 },
  { to: '/chatbot', label: 'Chatbot', icon: MessageSquare },
  { to: '/profile', label: 'Profile', icon: User },
];

export default function Layout() {
  const { userId, userName, logout } = useUser();
  const { themeMode, setThemeMode } = useTheme();
  const navigate = useNavigate();

  const themeOptions = [
    { value: 'light', label: 'Light', icon: Sun },
    { value: 'dark', label: 'Dark', icon: Moon },
    { value: 'system', label: 'System', icon: Monitor },
  ];

  return (
    <div className="app-layout topnav-layout">
      <header className="topbar">
        <div className="brand" onClick={() => navigate('/')}>
          <span className="logo">📚</span>
          <div>
            <strong>Study Assistant</strong>
            <small>Plan · Quiz · Progress</small>
          </div>
        </div>
        <nav className="topnav-links">
          {NAV.map(({ to, label }) => (
            <NavLink key={to} to={to} className={({ isActive }) => `topnav-link ${isActive ? 'active' : ''}`}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="topnav-user">
          <div className="theme-switcher" role="group" aria-label="Theme mode">
            {themeOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`theme-switch-btn ${themeMode === option.value ? 'active' : ''}`}
                onClick={() => setThemeMode(option.value)}
                aria-pressed={themeMode === option.value}
                title={`${option.label} mode`}
              >
                <option.icon size={14} />
                <span>{option.label}</span>
              </button>
            ))}
          </div>
          {userId ? (
            <>
              <span className="user-chip">{userName || userId.slice(0, 8)}</span>
              <button className="btn-outline btn-sm" onClick={logout}>
                <LogOut size={14} /> Logout
              </button>
            </>
          ) : (
            <button className="btn-primary btn-sm" onClick={() => navigate('/login')}>
              <User size={14} /> Login
            </button>
          )}
        </div>
      </header>

      <main className="main-content topnav-content">
        <Outlet />
      </main>
    </div>
  );
}
