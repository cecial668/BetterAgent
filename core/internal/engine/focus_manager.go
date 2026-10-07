package engine

import (
	"sync"
	"time"

	"go.uber.org/zap"
)

// FocusPhase is the lifecycle stage of one pomodoro/focus session.
type FocusPhase string

const (
	FocusPhaseIdle      FocusPhase = "idle"
	FocusPhaseRunning   FocusPhase = "running"
	FocusPhasePaused    FocusPhase = "paused"
	FocusPhaseCompleted FocusPhase = "completed"
)

// FocusState is the authoritative snapshot of a chat's focus session. It is
// broadcast to browsers (WS agent.focus_state) and to the cognitive engine
// (NATS agent.focus.state) on every change, and answered to status queries.
// RemainingSeconds is computed at snapshot time, so consumers never do clock
// math of their own for correctness (frontends count down locally for
// smoothness but reconcile against every broadcast).
type FocusState struct {
	ChatID           int64      `json:"chat_id"`
	Phase            FocusPhase `json:"phase"`
	PlannedMinutes   int        `json:"planned_minutes"`
	RemainingSeconds int        `json:"remaining_seconds"`
	StartedAtUnix    int64      `json:"started_at_unix,omitempty"`
	DeadlineUnix     int64      `json:"deadline_unix,omitempty"`
	// ElapsedSeconds excludes paused time; progress bars can use it directly.
	ElapsedSeconds int `json:"elapsed_seconds"`
}

type focusSession struct {
	phase          FocusPhase
	plannedMinutes int
	startedAt      time.Time
	// deadline is only meaningful while running; remaining only while paused.
	deadline  time.Time
	remaining time.Duration
	timer     *time.Timer
}

// FocusManager owns per-chat focus/pomodoro timers. It deliberately knows
// nothing about transport: callers register callbacks and the manager
// notifies them after every state change (never while holding the lock).
//
// While a session is running or paused the rest of the system must treat the
// chat as "do not disturb": PublishProactiveTurn refuses to fire and the
// gateway skips greetings (see IsActive).
type FocusManager struct {
	mu       sync.Mutex
	sessions map[int64]*focusSession
	logger   *zap.Logger

	onChange   func(FocusState)
	onComplete func(FocusState)
}

func NewFocusManager(logger *zap.Logger) *FocusManager {
	if logger == nil {
		logger = zap.NewNop()
	}
	return &FocusManager{
		sessions: make(map[int64]*focusSession),
		logger:   logger,
	}
}

// SetOnChange registers the listener called after every state mutation
// (start/pause/resume/end/natural-completion and heartbeat re-broadcasts).
func (m *FocusManager) SetOnChange(cb func(FocusState)) {
	m.mu.Lock()
	m.onChange = cb
	m.mu.Unlock()
}

// SetOnComplete registers the listener called once when a timer runs out
// naturally. Separate from onChange so the caller can trigger the
// "time is up, ask about what got done" turn exactly once.
func (m *FocusManager) SetOnComplete(cb func(FocusState)) {
	m.mu.Lock()
	m.onComplete = cb
	m.mu.Unlock()
}

// Start begins a new session (replacing any previous one for the chat).
func (m *FocusManager) Start(chatID int64, minutes int) FocusState {
	if minutes < 1 {
		minutes = 1
	}
	if minutes > 240 {
		minutes = 240
	}
	return m.start(chatID, minutes, time.Duration(minutes)*time.Minute)
}

// start allows tests to supply their own wall duration while keeping the
// user-visible planned minutes independent.
func (m *FocusManager) start(chatID int64, minutes int, duration time.Duration) FocusState {
	now := time.Now()

	m.mu.Lock()
	if old, ok := m.sessions[chatID]; ok && old.timer != nil {
		old.timer.Stop()
	}
	session := &focusSession{
		phase:          FocusPhaseRunning,
		plannedMinutes: minutes,
		startedAt:      now,
		deadline:       now.Add(duration),
	}
	m.sessions[chatID] = session
	session.timer = time.AfterFunc(duration, func() { m.complete(chatID) })
	state := m.stateLocked(chatID, now)
	m.mu.Unlock()

	m.logger.Info("focus session started",
		zap.Int64("chat_id", chatID),
		zap.Int("planned_minutes", minutes),
	)
	m.emit(state, false)
	return state
}

// Pause freezes the remaining time. No-op when not running.
func (m *FocusManager) Pause(chatID int64) FocusState {
	now := time.Now()

	m.mu.Lock()
	session, ok := m.sessions[chatID]
	if !ok || session.phase != FocusPhaseRunning {
		state := m.stateLocked(chatID, now)
		m.mu.Unlock()
		return state
	}
	if session.timer != nil {
		session.timer.Stop()
		session.timer = nil
	}
	session.remaining = session.deadline.Sub(now)
	if session.remaining < 0 {
		session.remaining = 0
	}
	session.phase = FocusPhasePaused
	state := m.stateLocked(chatID, now)
	remainingSeconds := int(session.remaining.Seconds())
	m.mu.Unlock()

	m.logger.Info("focus session paused",
		zap.Int64("chat_id", chatID),
		zap.Int("remaining_seconds", remainingSeconds),
	)
	m.emit(state, false)
	return state
}

// Resume restarts the timer from the frozen remaining time. No-op otherwise.
func (m *FocusManager) Resume(chatID int64) FocusState {
	now := time.Now()

	m.mu.Lock()
	session, ok := m.sessions[chatID]
	if !ok || session.phase != FocusPhasePaused {
		state := m.stateLocked(chatID, now)
		m.mu.Unlock()
		return state
	}
	session.phase = FocusPhaseRunning
	session.deadline = now.Add(session.remaining)
	remaining := session.remaining
	session.timer = time.AfterFunc(remaining, func() { m.complete(chatID) })
	state := m.stateLocked(chatID, now)
	m.mu.Unlock()

	m.logger.Info("focus session resumed", zap.Int64("chat_id", chatID))
	m.emit(state, false)
	return state
}

// End clears the session (used for both "recorded" and "abandoned" endings).
// It broadcasts the resulting idle state so every widget hides itself.
func (m *FocusManager) End(chatID int64) FocusState {
	now := time.Now()

	m.mu.Lock()
	session, ok := m.sessions[chatID]
	if ok {
		if session.timer != nil {
			session.timer.Stop()
		}
		delete(m.sessions, chatID)
	}
	state := m.stateLocked(chatID, now)
	m.mu.Unlock()

	if ok {
		m.logger.Info("focus session ended", zap.Int64("chat_id", chatID), zap.String("phase", string(session.phase)))
		m.emit(state, false)
	}
	return state
}

// complete fires when the timer runs out naturally. The session is kept in
// the completed phase until a finish/end command arrives, so a browser that
// was reloading at that moment can still render the completion form.
func (m *FocusManager) complete(chatID int64) {
	now := time.Now()

	m.mu.Lock()
	session, ok := m.sessions[chatID]
	if !ok || session.phase != FocusPhaseRunning {
		m.mu.Unlock()
		return
	}
	session.phase = FocusPhaseCompleted
	session.remaining = 0
	session.deadline = time.Time{}
	session.timer = nil
	state := m.stateLocked(chatID, now)
	m.mu.Unlock()

	m.logger.Info("focus session completed naturally", zap.Int64("chat_id", chatID))
	m.emit(state, true)
}

// State returns the current snapshot, or a zero-value idle state.
func (m *FocusManager) State(chatID int64) FocusState {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.stateLocked(chatID, time.Now())
}

// IsActive reports whether the chat is mid-focus (running or paused) and
// must therefore be shielded from proactive messages.
func (m *FocusManager) IsActive(chatID int64) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	session, ok := m.sessions[chatID]
	if !ok {
		return false
	}
	return session.phase == FocusPhaseRunning || session.phase == FocusPhasePaused
}

// Snapshot returns every non-idle session, for heartbeat re-broadcasts that
// let a restarted cognitive service (re)learn the current states.
func (m *FocusManager) Snapshot() []FocusState {
	now := time.Now()
	m.mu.Lock()
	defer m.mu.Unlock()
	states := make([]FocusState, 0, len(m.sessions))
	for chatID := range m.sessions {
		states = append(states, m.stateLocked(chatID, now))
	}
	return states
}

// StartHeartbeat re-broadcasts active states every interval until stop is
// called. This is belt-and-suspenders for consumers that (re)started mid-
// session and missed the transition events.
func (m *FocusManager) StartHeartbeat(interval time.Duration) (stop func()) {
	ticker := time.NewTicker(interval)
	done := make(chan struct{})
	go func() {
		for {
			select {
			case <-ticker.C:
				for _, state := range m.Snapshot() {
					m.mu.Lock()
					cb := m.onChange
					m.mu.Unlock()
					if cb != nil {
						cb(state)
					}
				}
			case <-done:
				ticker.Stop()
				return
			}
		}
	}()
	return func() { close(done) }
}

func (m *FocusManager) stateLocked(chatID int64, now time.Time) FocusState {
	session, ok := m.sessions[chatID]
	if !ok {
		return FocusState{ChatID: chatID, Phase: FocusPhaseIdle}
	}

	remaining := session.remaining
	if session.phase == FocusPhaseRunning {
		remaining = session.deadline.Sub(now)
		if remaining < 0 {
			remaining = 0
		}
	}
	if session.phase == FocusPhaseCompleted {
		remaining = 0
	}

	state := FocusState{
		ChatID:           chatID,
		Phase:            session.phase,
		PlannedMinutes:   session.plannedMinutes,
		RemainingSeconds: int(remaining.Round(time.Second).Seconds()),
		StartedAtUnix:    session.startedAt.Unix(),
	}
	if session.phase == FocusPhaseRunning {
		state.DeadlineUnix = session.deadline.Unix()
	}
	elapsed := time.Duration(session.plannedMinutes)*time.Minute - remaining
	if elapsed < 0 {
		elapsed = 0
	}
	state.ElapsedSeconds = int(elapsed.Round(time.Second).Seconds())
	return state
}

// emit notifies listeners outside the lock. complete additionally fires the
// completion callback exactly once per natural finish.
func (m *FocusManager) emit(state FocusState, completed bool) {
	m.mu.Lock()
	onChange := m.onChange
	onComplete := m.onComplete
	m.mu.Unlock()

	if onChange != nil {
		onChange(state)
	}
	if completed && onComplete != nil {
		onComplete(state)
	}
}
