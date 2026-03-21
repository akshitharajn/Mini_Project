import React from 'react';
import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';
import Dashboard from './pages/Dashboard';
import Profile from './pages/Profile';
import Login from './pages/Login';
import Subjects from './pages/Subjects';
import Schedule from './pages/Schedule';
import Progress from './pages/Progress';
import Quiz from './pages/Quiz';
import Chatbot from './pages/Chatbot';
import MindMap from './pages/MindMap';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/login" element={<Login />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/subjects" element={<Subjects />} />
        <Route path="/schedule" element={<Schedule />} />
        <Route path="/progress" element={<Progress />} />
        <Route path="/quiz" element={<Quiz />} />
        <Route path="/mind-map" element={<MindMap />} />
        <Route path="/chatbot" element={<Chatbot />} />
      </Route>
    </Routes>
  );
}
