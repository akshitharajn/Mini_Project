import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useUser } from '../context/UserContext';
import RequireUser from '../components/RequireUser';
import {
  generateSchedule,
  getSchedule,
  completeEntry,
  skipEntry,
  readyTopicForQuizzes,
} from '../services/api';
import toast from 'react-hot-toast';
import { RefreshCw } from 'lucide-react';

export default function Schedule() {
  const { userId, logout } = useUser();
  const [entries, setEntries] = useState([]);
  const [entryLoading, setEntryLoading] = useState({});
  const [loading, setLoading] = useState(false);
  const defaultStartDate = new Date().toISOString().slice(0, 10);
  const defaultEndDate = new Date(Date.now() + 14 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const navigate = useNavigate();

  const [startDate, setStartDate] = useState(defaultStartDate);
  const [endDate, setEndDate] = useState(defaultEndDate);
  const [startTime, setStartTime] = useState('08:00');
  const [dailyHours, setDailyHours] = useState(4);
  const [session, setSession] = useState(60);
  const [breakMins, setBreakMins] = useState(15);
  const [coverageEndDate, setCoverageEndDate] = useState('');

  const loadSchedule = async () => {
    if (!userId) return;
    try {
      const { data } = await getSchedule(userId);
      setEntries(data);
      setCoverageEndDate('');
    } catch (err) {
      if (err.response?.status === 404) {
        logout();
        toast.error('Your saved session is no longer valid. Sign in again.');
      }
    }
  };

  useEffect(() => {
    loadSchedule();
  }, [userId]);

  const handleComplete = async (entry) => {
    setEntryLoading((prev) => ({ ...prev, [entry.id]: true }));
    try {
      await completeEntry(entry.id);
      toast.success('Marked session read');
      loadSchedule();
      if (entry.topic_id) {
        try {
          const { data } = await readyTopicForQuizzes(entry.topic_id, {
            user_id: userId,
            num_questions: 5,
          });
          navigate('/quiz', {
            state: { readyQuizzes: data.quizzes, topicId: entry.topic_id },
          });
        } catch (err) {
          toast.error(err.response?.data?.detail || 'Quiz generation failed');
        }
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Could not mark read');
    } finally {
      setEntryLoading((prev) => ({ ...prev, [entry.id]: false }));
    }
  };

  const handleSkip = async (entry) => {
    setEntryLoading((prev) => ({ ...prev, [entry.id]: true }));
    try {
      await skipEntry(entry.id);
      toast.success('Session skipped and rescheduled');
      loadSchedule();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to skip session');
    } finally {
      setEntryLoading((prev) => ({ ...prev, [entry.id]: false }));
    }
  };

  const handleTakeQuiz = async (entry) => {
    if (!userId || !entry.topic_id) return;
    setEntryLoading((prev) => ({ ...prev, [entry.id]: true }));
    try {
      const { data } = await readyTopicForQuizzes(entry.topic_id, {
        user_id: userId,
        num_questions: 5,
      });
      navigate('/quiz', {
        state: { readyQuizzes: data.quizzes, topicId: entry.topic_id },
      });
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Could not start quiz');
    } finally {
      setEntryLoading((prev) => ({ ...prev, [entry.id]: false }));
    }
  };

  const handleGenerate = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await generateSchedule({
        user_id: userId,
        start_date: startDate,
        end_date: endDate,
        daily_start_time: `${startTime}:00`,
        daily_study_hours: dailyHours,
        session_duration_mins: session,
        break_duration_mins: breakMins,
      });
      setEntries(data);
      const generatedLastDate = data.reduce(
        (latest, entry) => (!latest || entry.scheduled_date > latest ? entry.scheduled_date : latest),
        '',
      );
      const extendedBeyondRequested = generatedLastDate && generatedLastDate > endDate;
      setCoverageEndDate(extendedBeyondRequested ? generatedLastDate : '');
      toast.success(
        extendedBeyondRequested
          ? `Generated ${data.length} study sessions through ${generatedLastDate} to cover the full syllabus.`
          : `Generated ${data.length} study sessions!`,
      );
    } catch (err) {
      if (err.response?.status === 404) {
        logout();
        toast.error('Your saved session is no longer valid. Sign in again.');
      } else if (err.response?.status === 400) {
        toast.error(err.response?.data?.detail || 'Add subjects and topics before generating a schedule.');
      } else {
        toast.error(err.response?.data?.detail || 'Error generating schedule');
      }
    } finally {
      setLoading(false);
    }
  };

  const grouped = entries.reduce((acc, entry) => {
    const dateKey = entry.scheduled_date;
    if (!acc[dateKey]) acc[dateKey] = [];
    acc[dateKey].push(entry);
    return acc;
  }, {});

  return (
    <RequireUser>
      <div className="page">
        <h1 className="page-title">Study Schedule</h1>

        <form className="card form" onSubmit={handleGenerate}>
          <h3>Generate Schedule</h3>
          <div className="form-row">
            <div className="form-group">
              <label>Start date</label>
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </div>
            <div className="form-group">
              <label>End date</label>
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Start time</label>
              <input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Daily study hours</label>
              <input
                type="number"
                min="0.5"
                max="16"
                step="0.5"
                value={dailyHours}
                onChange={(e) => setDailyHours(+e.target.value)}
              />
            </div>
            <div className="form-group">
              <label>Session (min)</label>
              <input
                type="number"
                min="15"
                max="180"
                step="15"
                value={session}
                onChange={(e) => setSession(+e.target.value)}
              />
            </div>
            <div className="form-group">
              <label>Break (min)</label>
              <input
                type="number"
                min="5"
                max="60"
                step="5"
                value={breakMins}
                onChange={(e) => setBreakMins(+e.target.value)}
              />
            </div>
          </div>
          <button className="btn btn-primary" type="submit" disabled={loading}>
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
            {loading ? ' Generating...' : ' Generate Schedule'}
          </button>
        </form>

        {coverageEndDate && (
          <div className="card" style={{ marginTop: '1rem' }}>
            <p style={{ margin: 0 }}>
              The plan extends through <strong>{coverageEndDate}</strong> so all syllabus topics are covered.
            </p>
          </div>
        )}

        {Object.keys(grouped).length === 0 && (
          <p className="text-muted" style={{ marginTop: '1rem' }}>
            No schedule yet - generate one above.
          </p>
        )}

        {Object.entries(grouped).map(([date, items]) => (
          <div key={date} className="card" style={{ marginTop: '1rem' }}>
            <h3>{date}</h3>
            <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Subject</th>
                <th>Topic</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((entry) => (
                <tr
                  key={entry.id}
                  className={`schedule-row ${entry.completed ? 'schedule-row-completed' : ''}`}
                >
                  <td>
                    {entry.start_time?.slice(0, 5)} - {entry.end_time?.slice(0, 5)}
                  </td>
                  <td>{entry.subject_name}</td>
                  <td>{entry.topic_name}</td>
                  <td className="schedule-actions-cell">
                    <div className="schedule-actions">
                      <div className="schedule-actions-top">
                        <button
                          type="button"
                          className={`btn btn-xs schedule-action-btn ${entry.completed ? 'btn-success' : 'btn-outline'}`}
                          disabled={entryLoading[entry.id] || entry.completed}
                          onClick={() => handleComplete(entry)}
                        >
                          {entryLoading[entry.id] ? 'Working…' : 'Read'}
                        </button>
                        <button
                          type="button"
                          className="btn btn-xs btn-outline schedule-action-btn"
                          disabled={entryLoading[entry.id]}
                          onClick={() => handleSkip(entry)}
                        >
                          Skip
                        </button>
                      </div>
                      <div className="schedule-actions-bottom">
                        <button
                          type="button"
                          className="btn btn-xs btn-primary schedule-action-btn schedule-action-quiz"
                          disabled={entryLoading[entry.id]}
                          onClick={() => handleTakeQuiz(entry)}
                        >
                          Take Quiz
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </RequireUser>
  );
}
