import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useUser } from '../context/UserContext';
import {
  Sparkles,
  CalendarDays,
  BarChart3,
  FileQuestion,
  Rocket,
  ShieldCheck,
  PlayCircle,
  RefreshCcw,
  Zap,
  MessageSquare,
} from 'lucide-react';

const FEATURE_CARDS = [
  {
    title: 'Adaptive scheduling',
    body: 'Build day-level sprints that reshuffle automatically when plans slip.',
    icon: CalendarDays,
  },
  {
    title: 'Progress intelligence',
    body: 'Surface weak topics instantly, with micro reviews booked for you.',
    icon: BarChart3,
  },
  {
    title: 'Groq-powered quizzes',
    body: 'Topic-grounded, level-aware questions with no repeats or filler.',
    icon: FileQuestion,
  },
];

const QUICK_ACTIONS = [
  { label: "Start today's plan", icon: PlayCircle, route: '/schedule' },
  { label: 'Generate quiz', icon: FileQuestion, route: '/quiz' },
  { label: 'View dashboard', icon: BarChart3, route: '/dashboard' },
  { label: 'Student profile', icon: ShieldCheck, route: '/profile' },
];

const FLOW = [
  { title: 'Plan', text: 'Set subjects, daily bandwidth, and let the system auto-sequence your day.', icon: CalendarDays },
  { title: 'Practice', text: 'Groq-first quizzes by topic and difficulty; no stem repeats.', icon: RefreshCcw },
  { title: 'Chat', text: 'Ask concept questions and get concise, context-aware answers.', icon: MessageSquare },
  { title: 'Adjust', text: 'Auto re-plan when you skip/complete items; keep momentum.', icon: Zap },
];

export default function Home() {
  const { userId } = useUser();
  const navigate = useNavigate();

  const primaryCta = () => {
    if (!userId) return () => navigate('/login');
    return () => navigate('/schedule');
  };

  const secondaryCta = () => {
    if (!userId) return () => navigate('/profile');
    return () => navigate('/dashboard');
  };

  return (
    <div className="page home">
      <section className="hero">
        <div className="hero-copy">
          <div className="badge">
            <Sparkles size={16} /> Study OS, rethought
          </div>
          <h1>Plan, quiz, and stay on track in one focused workspace.</h1>
          <p>
            Build adaptive study days, launch Groq-powered quizzes by topic and difficulty, and get crisp answers that stay within your study plan.
          </p>
          <div className="hero-actions">
            <button className="btn btn-primary lg" onClick={primaryCta()}>
              Start now
            </button>
            <button className="btn btn-ghost lg" onClick={secondaryCta()}>
              View dashboard
            </button>
          </div>
          <div className="stat-bar">
            <div><strong>Groq quizzes</strong><span>Topic-grounded · Level-wise</span></div>
            <div><strong>Smart chat</strong><span>Education-only, plan-aware</span></div>
            <div><strong>No repeats</strong><span>Smart dedupe per topic/user</span></div>
          </div>
          <div className="hero-meta">
            <div>
              <strong>Real-time re-planning</strong>
              <span>Days rebalance automatically when a block slips.</span>
            </div>
            <div>
              <strong>Level-wise quizzes</strong>
              <span>Groq-first, topic-grounded, no repeats.</span>
            </div>
            <div>
              <strong>Snap insights</strong>
              <span>Weak-topic nudges with micro review slots.</span>
            </div>
          </div>
        </div>
        <div className="hero-panel">
          <div className="panel-card">
            <div className="panel-head">
              <span>Today’s plan</span>
              <Rocket size={18} />
            </div>
            <ul className="panel-list">
              <li>
                <span className="pill pill-primary">Focus</span>
                <div>
                  <p>Deep work block · 90 mins</p>
                  <small>Active recall + spaced practice</small>
                </div>
              </li>
              <li>
                <span className="pill pill-amber">Quiz</span>
                <div>
                  <p>DBMS — Easy level</p>
                  <small>5 topic-specific questions</small>
                </div>
              </li>
              <li>
                <span className="pill pill-sage">Review</span>
                <div>
                  <p>Weak topic refresh</p>
                  <small>Micro revision session scheduled</small>
                </div>
              </li>
            </ul>
            <div className="panel-foot">
              <div>
                <strong>Completion</strong>
                <p>68%</p>
              </div>
              <div>
                <strong>Next up</strong>
                <p>Groq quiz · Easy · 5 Qs</p>
              </div>
            </div>
          </div>
          <div className="trust">
            <ShieldCheck size={16} />
            Instant scoring, no data leaves your plan workspace.
          </div>
        </div>
      </section>

      <section className="quick-actions-rail">
        {QUICK_ACTIONS.map((qa) => (
          <button key={qa.label} className="qa-tile" onClick={() => navigate(qa.route)}>
            <qa.icon size={18} />
            <span>{qa.label}</span>
          </button>
        ))}
      </section>

      <section className="feature-grid">
        {FEATURE_CARDS.map((f) => (
          <div key={f.title} className="feature-card">
            <div className="feature-icon">
              <f.icon size={18} />
            </div>
            <h3>{f.title}</h3>
            <p>{f.body}</p>
          </div>
        ))}
      </section>

      <section className="two-col">
        <div className="stack-card">
          <h3>How it works</h3>
          <ol>
            <li>Set your subjects and daily study bandwidth.</li>
            <li>Generate adaptive schedules that reorder when you fall behind.</li>
            <li>Take level-wise quizzes (Groq-first, rule-based fallback) with no repeats.</li>
            <li>Act on weak-topic nudges and micro review sessions.</li>
          </ol>
        </div>
        <div className="stack-card highlight">
          <h3>Built for momentum</h3>
          <p>
            Every surface is tuned for clarity: glass cards, bold typography, and focused actions. Move
            from plan ? practice ? feedback in minutes.
          </p>
        </div>
      </section>

      <section className="two-col" style={{ marginTop: '1rem' }}>
        <div className="stack-card highlight">
          <h3>Your student profile</h3>
          <p style={{ marginBottom: '0.6rem' }}>
            Keep your goals, daily availability, and target exam dates in one place. Update it to improve schedule quality.
          </p>
          <div style={{ display: 'grid', gap: '0.4rem', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
            <div className="profile-chip">
              <strong>Subjects</strong>
              <span>All tracked with priorities</span>
            </div>
            <div className="profile-chip">
              <strong>Daily hours</strong>
              <span>Flexible per weekday</span>
            </div>
            <div className="profile-chip">
              <strong>Goals</strong>
              <span>Exam dates & focus areas</span>
            </div>
          </div>
          <div style={{ marginTop: '0.8rem' }}>
            <button className="btn btn-primary" onClick={() => navigate('/profile')}>
              Open profile
            </button>
          </div>
        </div>
        <div className="flow-card" style={{ minHeight: '100%' }}>
          <ShieldCheck size={18} />
          <div>
            <h4>Privacy-first</h4>
            <p>Data stays in your workspace; exports are optional and explicit.</p>
          </div>
        </div>
      </section>

      <section className="flow-grid">
        {FLOW.map((step) => (
          <div key={step.title} className="flow-card">
            <step.icon size={18} />
            <div>
              <h4>{step.title}</h4>
              <p>{step.text}</p>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
