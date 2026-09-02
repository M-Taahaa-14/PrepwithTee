/* tour-dashboard.js — guided walkthrough for the Dashboard page.
 *
 * Imported by dashboard.html. Checks for ?tour=1 in the URL and
 * auto-starts the tour. Also exported as startDashboardTour() so the
 * "Get Started" checklist panel can re-trigger it on demand.
 *
 * On completion, sets the "tour_dashboard" flag so the checklist row
 * turns green.
 */

import { startTour, autoStartTour } from "/tour-engine.js";
import { setFlag }                   from "/onboarding.js";
import { getUser }                   from "/auth.js";

const STEPS = [
  // 1 — Hero bar
  {
    element:  ".hub-hero",
    title:    "Welcome to your Dashboard",
    body:     "This is your study command centre. Your level, XP progress, streak, and daily focus sessions all live in this strip at the top.",
    position: "bottom",
  },
  // 2 — XP / level chip
  {
    element:  ".hub-xp-row",
    title:    "XP & Levels",
    body:     "Every action earns XP — completing missions, running focus sessions, practising MCQs. XP builds up permanently and unlocks higher levels over time.",
    position: "bottom",
  },
  // 3 — Missions
  {
    element:  ".hub-mission-card",
    title:    "Today's Mission",
    body:     "Four short tasks, refreshed each day. Tick one off and earn XP instantly. Complete all four to fill the progress bar and unlock bonus rewards.",
    position: "right",
  },
  // 4 — Subject rings
  {
    element:  "#ring-row",
    title:    "Your Subjects",
    body:     "Each ring shows how confident you are across a subject's chapters. Green = confident, orange = in progress, grey = not started. Tap a ring to jump into progress tracker.",
    position: "auto",
  },
  // 5 — Continue learning
  {
    element:  ".hub-continue-card",
    title:    "Continue Learning",
    body:     "Your most recently visited chapters appear here so you can pick up exactly where you left off.",
    position: "right",
  },
  // 6 — Heatmap
  {
    element:  ".hub-heatmap-card",
    title:    "Study Activity Heatmap",
    body:     "Every day you study adds a coloured square. The darker the square, the more XP you earned that day. Aim to keep the grid green!",
    position: "right",
  },
  // 7 — Exam Countdown
  {
    element:  ".hub-countdown-card",
    title:    "Exam Countdown",
    body:     "Add your Cambridge exam dates and a live countdown appears here. It stays visible every time you open the dashboard to keep you on track.",
    position: "auto",
  },
  // 8 — Insights
  {
    element:  ".hub-insights-card",
    title:    "Personalised Insights",
    body:     "As you study, the dashboard learns your patterns and surfaces tips: which topics need more attention, when your best focus time is, and more.",
    position: "auto",
  },
  // 9 — Recent Practice
  {
    element:  ".hub-practice-card",
    title:    "Recent Practice",
    body:     "Your last quiz and MCQ sessions appear here. One tap continues from where you stopped.",
    position: "auto",
  },
  // 10 — Homework
  {
    element:  ".hub-homework-card",
    title:    "Homework",
    body:     "On the Tutoring plan, tasks assigned by your teacher appear here with due dates and submission links.",
    position: "auto",
  },
  // 11 — Focus Timer
  {
    element:  ".hub-focus-card",
    title:    "Focus Mode (Pomodoro Timer)",
    body:     "25 minutes of deep work, then a 5-minute break. Hit Start and the timer runs. Completing a full session earns 40 XP and counts toward your daily missions.",
    position: "left",
  },
  // 12 — Quick actions
  {
    element:  ".hub-quick-card",
    title:    "Jump In",
    body:     "One-tap shortcuts to your most useful tools — AI Tutor, past papers, formula sheets, and more.",
    position: "left",
  },
  // 13 — Badges
  {
    element:  ".hub-achievements-card",
    title:    "Achievements",
    body:     "Unlock badges by hitting milestones — first study session, 7-day streak, 1,000 XP, and more. Locked badges show you what to aim for next.",
    position: "left",
  },
  // 14 — Sticky Notes / Reminders
  {
    element:  ".hub-sticky-card",
    title:    "Sticky Notes",
    body:     "Jot down anything — a formula to memorise, a topic to revisit, a reminder from your teacher. Notes persist across sessions.",
    position: "left",
  },
  // 15 — Calendar + Tasks (now at the bottom)
  {
    element:  ".hub-bigcal-section",
    title:    "Calendar & Tasks",
    body:     "Plan ahead with your personal study calendar. Add tasks with due dates — they appear on the calendar so you can see your full week at a glance.",
    position: "top",
  },
  // 16 — Enrol
  {
    element:  "#enrol-grid",
    title:    "Add a Subject",
    body:     "Tap any subject card to enrol. This unlocks chapter tracking, topical past papers, AI quizzes, and MCQ practice for that syllabus — all free.",
    position: "top",
  },
];

async function _markSeen() {
  const user = await getUser();
  if (user) setFlag(user, "tour_dashboard");
}

export function startDashboardTour() {
  startTour(STEPS, { label: "Dashboard", onComplete: _markSeen, onSkip: _markSeen });
}

export function initDashboardTour() {
  autoStartTour(STEPS, { label: "Dashboard", onComplete: _markSeen, onSkip: _markSeen });
}
