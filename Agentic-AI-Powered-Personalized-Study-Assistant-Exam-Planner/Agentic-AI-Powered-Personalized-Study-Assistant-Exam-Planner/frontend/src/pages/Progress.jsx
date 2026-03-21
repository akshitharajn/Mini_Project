import React, { useEffect, useState } from 'react';
import { useUser } from '../context/UserContext';
import RequireUser from '../components/RequireUser';
import MetricCard from '../components/MetricCard';
import { getProgressDashboard, updateProgress } from '../services/api';
import toast from 'react-hot-toast';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import { BookOpen, CheckCircle2, TrendingUp, Clock } from 'lucide-react';

const COLORS = ['#10b981', '#f59e0b', '#ef4444'];

export default function Progress() {
  const { userId } = useUser();
  const [dashboard, setDashboard] = useState(null);

  // Log form
  const [topicId, setTopicId] = useState('');
  const [comp, setComp] = useState(50);
  const [mins, setMins] = useState(30);
  const [notes, setNotes] = useState('');

  const load = async () => {
    try {
      const { data } = await getProgressDashboard(userId);
      setDashboard(data);
    } catch {}
  };

  useEffect(() => {
    if (userId) load();
  }, [userId]);

  const handleLog = async (e) => {
    e.preventDefault();
    try {
      await updateProgress({
        user_id: userId,
        topic_id: topicId,
        completion_pct: comp,
        time_spent_mins: mins,
        notes: notes || null,
      });
      toast.success('Progress recorded!');
      setTopicId('');
      setNotes('');
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Error');
    }
  };

  const pieData = dashboard
    ? [
        { name: 'Completed', value: dashboard.completed_topics },
        {
          name: 'In Progress',
          value: dashboard.total_topics - dashboard.completed_topics - (dashboard.weak_topics?.length || 0),
        },
        { name: 'Weak', value: dashboard.weak_topics?.length || 0 },
      ].filter((d) => d.value > 0)
    : [];

  return (
    <RequireUser>
      <div className="page">
        <h1 className="page-title">📊 Progress &amp; Analytics</h1>

        {/* Log session */}
        <form className="card form" onSubmit={handleLog}>
          <h3>Log Study Session</h3>
          <div className="form-row">
            <div className="form-group" style={{ flex: 2 }}>
              <label>Topic ID</label>
              <input value={topicId} onChange={(e) => setTopicId(e.target.value)} required />
            </div>
            <div className="form-group">
              <label>Completion %: {comp}</label>
              <input
                type="range"
                min="0"
                max="100"
                value={comp}
                onChange={(e) => setComp(+e.target.value)}
              />
            </div>
            <div className="form-group">
              <label>Time (min)</label>
              <input
                type="number"
                min="0"
                step="5"
                value={mins}
                onChange={(e) => setMins(+e.target.value)}
              />
            </div>
          </div>
          <div className="form-group">
            <label>Notes</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
          </div>
          <button className="btn btn-primary" type="submit">📝 Log Progress</button>
        </form>

        {/* Dashboard */}
        {dashboard && (
          <>
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

            {/* Charts row */}
            <div className="charts-row">
              {/* Progress bar chart */}
              <div className="card chart-card">
                <h3>Overall Progress</h3>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart
                    data={[
                      { name: 'Overall', value: dashboard.overall_completion_pct },
                      {
                        name: 'Avg Quiz',
                        value: dashboard.average_quiz_score ?? 0,
                      },
                    ]}
                  >
                    <XAxis dataKey="name" />
                    <YAxis domain={[0, 100]} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#4A90D9" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Pie chart */}
              <div className="card chart-card">
                <h3>Topic Distribution</h3>
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                      {pieData.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            {dashboard.weak_topics?.length > 0 && (
              <div className="card card-warning">
                <h3>⚠️ Weak Topics</h3>
                <ul>
                  {dashboard.weak_topics.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </div>
            )}

            {dashboard.average_quiz_score != null && (
              <div className="card card-info">
                📝 Average quiz score: <strong>{dashboard.average_quiz_score}%</strong>
              </div>
            )}
          </>
        )}
      </div>
    </RequireUser>
  );
}
