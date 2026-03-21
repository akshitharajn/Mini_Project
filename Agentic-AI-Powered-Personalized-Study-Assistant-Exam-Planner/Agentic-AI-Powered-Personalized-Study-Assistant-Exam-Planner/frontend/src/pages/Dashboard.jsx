import React, { useEffect, useState } from 'react';
import { useUser } from '../context/UserContext';
import { getProgressDashboard } from '../services/api';
import MetricCard from '../components/MetricCard';
import {
  BookOpen,
  CheckCircle2,
  TrendingUp,
  Clock,
  CalendarDays,
  Brain,
  Mic,
  FileQuestion,
  Share2,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export default function Dashboard() {
  const { userId } = useUser();
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState(null);

  useEffect(() => {
    if (userId) {
      getProgressDashboard(userId)
        .then((r) => setDashboard(r.data))
        .catch(() => {});
    }
  }, [userId]);

  return (
    <div className="page">
      <h1 className="page-title">📚 Agentic AI Study Assistant &amp; Exam Planner</h1>

      {!userId ? (
        <div className="hero-card">
          <p>
            Welcome! This system uses <strong>agentic AI</strong> to generate dynamic study
            schedules, track your progress, and adapt plans in real time.
          </p>
          <div className="feature-grid">
            {[
              { icon: <CalendarDays size={24} />, text: 'Optimised study schedules' },
              { icon: <TrendingUp size={24} />, text: 'Progress tracking & analytics' },
              { icon: <Brain size={24} />, text: 'AI adaptive re-planning' },
              { icon: <FileQuestion size={24} />, text: 'Level-wise quizzes' },
              { icon: <Mic size={24} />, text: 'Voice interaction' },
              { icon: <CheckCircle2 size={24} />, text: 'Smart notifications' },
            ].map((f, i) => (
              <div key={i} className="feature-item">
                {f.icon}
                <span>{f.text}</span>
              </div>
            ))}
          </div>
          <button className="btn btn-primary" onClick={() => navigate('/profile')}>
            Get Started →
          </button>
        </div>
      ) : (
        <>
          {dashboard && (
            <div className="metrics-row">
              <MetricCard
                label="Total Topics"
                value={dashboard.total_topics}
                icon={<BookOpen size={20} />}
              />
              <MetricCard
                label="Completed"
                value={dashboard.completed_topics}
                icon={<CheckCircle2 size={20} />}
                color="#10b981"
              />
              <MetricCard
                label="Progress"
                value={`${dashboard.overall_completion_pct}%`}
                icon={<TrendingUp size={20} />}
                color="#f59e0b"
              />
              <MetricCard
                label="Study Time"
                value={`${Math.round(dashboard.total_time_spent_mins)} min`}
                icon={<Clock size={20} />}
                color="#8b5cf6"
              />
            </div>
          )}

          {dashboard?.weak_topics?.length > 0 && (
            <div className="card card-warning">
              <h3>⚠️ Weak Topics Needing Attention</h3>
              <ul>
                {dashboard.weak_topics.map((t, i) => (
                  <li key={i}>{t}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="quick-actions">
            <h3>Quick Actions</h3>
            <div className="action-grid">
              <button className="btn btn-outline" onClick={() => navigate('/schedule')}>
                <CalendarDays size={16} /> View Schedule
              </button>
              <button className="btn btn-outline" onClick={() => navigate('/quiz')}>
                <FileQuestion size={16} /> Take Quiz
              </button>
              <button className="btn btn-outline" onClick={() => navigate('/mind-map')}>
                <Share2 size={16} /> Mind Map
              </button>
              <button className="btn btn-outline" onClick={() => navigate('/agent')}>
                <Brain size={16} /> AI Insights
              </button>
              <button className="btn btn-outline" onClick={() => navigate('/progress')}>
                <TrendingUp size={16} /> Progress
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
