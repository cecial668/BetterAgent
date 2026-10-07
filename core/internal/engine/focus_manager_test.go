package engine

import (
	"sync"
	"testing"
	"time"

	"go.uber.org/zap"
)

func TestFocusManager_StartPauseResumeEnd(t *testing.T) {
	fm := NewFocusManager(zap.NewNop())

	state := fm.Start(1, 25)
	if state.Phase != FocusPhaseRunning {
		t.Fatalf("expected running after Start, got %s", state.Phase)
	}
	if state.PlannedMinutes != 25 {
		t.Errorf("expected planned_minutes=25, got %d", state.PlannedMinutes)
	}
	if state.RemainingSeconds < 25*60-5 || state.RemainingSeconds > 25*60 {
		t.Errorf("expected ~1500 remaining seconds, got %d", state.RemainingSeconds)
	}
	if !fm.IsActive(1) {
		t.Errorf("expected running session to be active")
	}

	paused := fm.Pause(1)
	if paused.Phase != FocusPhasePaused {
		t.Fatalf("expected paused, got %s", paused.Phase)
	}
	// Pausing twice must not move the frozen remaining time.
	pausedAgain := fm.Pause(1)
	if pausedAgain.RemainingSeconds != paused.RemainingSeconds || pausedAgain.Phase != FocusPhasePaused {
		t.Errorf("second Pause should be a no-op, got %s/%d", pausedAgain.Phase, pausedAgain.RemainingSeconds)
	}
	if !fm.IsActive(1) {
		t.Errorf("expected paused session to stay active (do-not-disturb)")
	}
	if paused.ElapsedSeconds > paused.PlannedMinutes*60 {
		t.Errorf("elapsed seconds should be clamped to planned time, got %d", paused.ElapsedSeconds)
	}

	resumed := fm.Resume(1)
	if resumed.Phase != FocusPhaseRunning {
		t.Fatalf("expected running after Resume, got %s", resumed.Phase)
	}
	if resumed.RemainingSeconds != paused.RemainingSeconds {
		t.Errorf("resume should keep the frozen remaining time: paused=%d resumed=%d", paused.RemainingSeconds, resumed.RemainingSeconds)
	}

	ended := fm.End(1)
	if ended.Phase != FocusPhaseIdle {
		t.Fatalf("expected idle after End, got %s", ended.Phase)
	}
	if fm.IsActive(1) {
		t.Errorf("expected ended session to be inactive")
	}
}

func TestFocusManager_NaturalCompletionFiresOnce(t *testing.T) {
	fm := NewFocusManager(zap.NewNop())

	var mu sync.Mutex
	var completed []FocusState
	changes := 0
	fm.SetOnComplete(func(s FocusState) {
		mu.Lock()
		completed = append(completed, s)
		mu.Unlock()
	})
	fm.SetOnChange(func(FocusState) {
		mu.Lock()
		changes++
		mu.Unlock()
	})

	fm.start(7, 1, 40*time.Millisecond)
	time.Sleep(250 * time.Millisecond)

	// Snapshot under the test lock, then release before calling manager
	// methods -- their callbacks take the same lock.
	mu.Lock()
	completedCount := len(completed)
	changesCount := changes
	var first FocusState
	if completedCount > 0 {
		first = completed[0]
	}
	mu.Unlock()

	if completedCount != 1 {
		t.Fatalf("expected exactly one completion callback, got %d", completedCount)
	}
	if first.Phase != FocusPhaseCompleted || first.RemainingSeconds != 0 {
		t.Errorf("unexpected completion state: %+v", first)
	}
	if first.StartedAtUnix <= 0 {
		t.Errorf("expected started_at to be stamped")
	}
	if fm.IsActive(7) {
		t.Errorf("a completed session must not count as active (focus is over)")
	}
	if changesCount < 2 {
		t.Errorf("expected onChange at start and completion, got %d calls", changesCount)
	}
	if state := fm.State(7); state.Phase != FocusPhaseCompleted {
		t.Errorf("expected completed state to persist until finish/end, got %s", state.Phase)
	}

	// End clears the completed session.
	if state := fm.End(7); state.Phase != FocusPhaseIdle {
		t.Errorf("expected idle after ending a completed session, got %s", state.Phase)
	}
	if state := fm.State(7); state.Phase != FocusPhaseIdle {
		t.Errorf("expected idle state after clear, got %s", state.Phase)
	}
}

func TestFocusManager_RestartReplacesOldTimer(t *testing.T) {
	fm := NewFocusManager(zap.NewNop())
	completed := false
	fm.SetOnComplete(func(FocusState) { completed = true })

	fm.start(3, 1, 40*time.Millisecond)
	time.Sleep(10 * time.Millisecond)
	fm.start(3, 5, 5*time.Second)

	time.Sleep(150 * time.Millisecond)
	if completed {
		t.Fatalf("restarting must cancel the previous timer")
	}
	if state := fm.State(3); state.Phase != FocusPhaseRunning || state.PlannedMinutes != 5 {
		t.Errorf("expected the new running session, got %+v", state)
	}
}

func TestFocusManager_SnapshotAndHeartbeat(t *testing.T) {
	fm := NewFocusManager(zap.NewNop())
	events := make(chan FocusState, 16)
	fm.SetOnChange(func(s FocusState) { events <- s })

	fm.Start(11, 30)
	fm.Start(22, 15)
	if got := len(fm.Snapshot()); got != 2 {
		t.Fatalf("expected 2 active sessions in snapshot, got %d", got)
	}

	stop := fm.StartHeartbeat(20 * time.Millisecond)
	deadline := time.After(time.Second)
	// Drain the two start events, then wait for two heartbeat re-broadcasts.
	for i := 0; i < 2; i++ {
		select {
		case <-events:
		case <-deadline:
			t.Fatalf("missing start event %d", i)
		}
	}
	for i := 0; i < 2; i++ {
		select {
		case <-events:
		case <-deadline:
			t.Fatalf("missing heartbeat event %d", i)
		}
	}
	stop()

	// Keep draining until after End: the heartbeat goroutine may be mid-send
	// (it blocks on a full channel with no locks held) and End's change
	// callback must not block forever behind it.
	drainDone := make(chan struct{})
	go func() {
		for {
			select {
			case <-events:
			case <-drainDone:
				return
			}
		}
	}()
	time.Sleep(60 * time.Millisecond)
	fm.End(11)
	fm.End(22)
	close(drainDone)

	if got := len(fm.Snapshot()); got != 0 {
		t.Errorf("expected empty snapshot after ending all sessions, got %d", got)
	}
}

func TestFocusManager_StartClampsMinutes(t *testing.T) {
	fm := NewFocusManager(zap.NewNop())
	if state := fm.Start(9, 0); state.PlannedMinutes != 1 {
		t.Errorf("expected minutes clamped to 1, got %d", state.PlannedMinutes)
	}
	if state := fm.Start(9, 999); state.PlannedMinutes != 240 {
		t.Errorf("expected minutes clamped to 240, got %d", state.PlannedMinutes)
	}
	fm.End(9)
}
