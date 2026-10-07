package webgateway

import (
	"encoding/json"
	"testing"

	"github.com/nats-io/nats.go"
	"go.uber.org/zap"
	"nhooyr.io/websocket"

	"betteragent-core/internal/engine"
)

func focusCommandMsg(t *testing.T, chatID int64, action string, minutes int) *nats.Msg {
	t.Helper()
	payload := map[string]any{"chat_id": chatID, "action": action}
	if minutes > 0 {
		payload["minutes"] = minutes
	}
	data, err := json.Marshal(map[string]any{"payload": payload})
	if err != nil {
		t.Fatalf("failed to marshal focus command: %v", err)
	}
	return &nats.Msg{Data: data}
}

func newFocusTestSession(chatID int64) *ClientSession {
	return &ClientSession{
		ID:       "focus-test-session",
		ChatID:   chatID,
		sendChan: make(chan WSFrame, 8),
		logger:   zap.NewNop(),
	}
}

func TestHandleFocusCommandMsg_Lifecycle(t *testing.T) {
	b, _ := newTestNatsBridge(t)
	focus := engine.NewFocusManager(zap.NewNop())
	b.SetFocusManager(focus)

	const chatID = int64(8101)

	b.handleFocusCommandMsg(focusCommandMsg(t, chatID, "start", 25))
	if state := focus.State(chatID); state.Phase != engine.FocusPhaseRunning || state.PlannedMinutes != 25 {
		t.Fatalf("expected running 25-minute session, got %+v", state)
	}
	if !focus.IsActive(chatID) {
		t.Fatalf("expected started session to be active")
	}

	b.handleFocusCommandMsg(focusCommandMsg(t, chatID, "pause", 0))
	if state := focus.State(chatID); state.Phase != engine.FocusPhasePaused {
		t.Fatalf("expected paused session, got %+v", state)
	}

	b.handleFocusCommandMsg(focusCommandMsg(t, chatID, "resume", 0))
	if state := focus.State(chatID); state.Phase != engine.FocusPhaseRunning {
		t.Fatalf("expected resumed session, got %+v", state)
	}

	b.handleFocusCommandMsg(focusCommandMsg(t, chatID, "end", 0))
	if state := focus.State(chatID); state.Phase != engine.FocusPhaseIdle {
		t.Fatalf("expected idle after end, got %+v", state)
	}
	if focus.IsActive(chatID) {
		t.Fatalf("expected ended session to be inactive")
	}

	// Unknown actions are ignored, not fatal.
	b.handleFocusCommandMsg(focusCommandMsg(t, chatID, "banana", 0))
	if state := focus.State(chatID); state.Phase != engine.FocusPhaseIdle {
		t.Fatalf("unknown action must not change state, got %+v", state)
	}
}

func TestPublishProactiveTurn_SuppressedDuringFocus(t *testing.T) {
	b, _ := newTestNatsBridge(t)
	focus := engine.NewFocusManager(zap.NewNop())
	b.SetFocusManager(focus)

	const chatID = int64(8102)
	focus.Start(chatID, 25)

	engine.PublishProactiveTurn(b.bus, b.csm, nil, nil, nil, focus, chatID, "测试主动搭话", b.logger)
	if got := b.csm.GetChatState(chatID); got != engine.StateIdle {
		t.Fatalf("expected proactive turn suppressed during focus (chat stays IDLE), got %s", got)
	}

	// Once focus is over the very same call must go through again.
	focus.End(chatID)
	engine.PublishProactiveTurn(b.bus, b.csm, nil, nil, nil, focus, chatID, "测试主动搭话", b.logger)
	if got := b.csm.GetChatState(chatID); got != engine.StateThinking {
		t.Fatalf("expected proactive turn allowed after focus ends, got %s", got)
	}
}

func TestHandleUserGreeting_SkippedDuringFocus(t *testing.T) {
	b, _ := newTestNatsBridge(t)
	focus := engine.NewFocusManager(zap.NewNop())
	b.SetFocusManager(focus)

	const chatID = int64(8103)
	focus.Start(chatID, 25)

	b.HandleUserWSMessage(newGreetingTestSession(chatID), websocket.MessageText, greetingFrame(t, nil))

	if got := b.csm.GetChatState(chatID); got != engine.StateIdle {
		t.Fatalf("expected greeting suppressed during focus (chat stays IDLE), got %s", got)
	}
}

func TestHandleNoticeMsg_BroadcastsToAllSessions(t *testing.T) {
	b, _ := newTestNatsBridge(t)
	s1 := newFocusTestSession(9001)
	s1.ID = "notice-session-1"
	s2 := newFocusTestSession(9002)
	s2.ID = "notice-session-2"
	b.sessions.Register(s1)
	b.sessions.Register(s2)

	data, err := json.Marshal(map[string]any{"payload": map[string]any{
		"level":   "info",
		"title":   "向着星",
		"message": "之前暂存的委托修改已经补交成功。",
	}})
	if err != nil {
		t.Fatalf("failed to marshal notice: %v", err)
	}
	b.handleNoticeMsg(&nats.Msg{Data: data})

	for _, session := range []*ClientSession{s1, s2} {
		select {
		case frame := <-session.sendChan:
			var wsMsg struct {
				Type    string         `json:"type"`
				Payload map[string]any `json:"payload"`
			}
			if err := json.Unmarshal(frame.Data, &wsMsg); err != nil {
				t.Fatalf("failed to unmarshal notice frame: %v", err)
			}
			if wsMsg.Type != "agent.notice" {
				t.Errorf("expected agent.notice frame, got %s", wsMsg.Type)
			}
			if wsMsg.Payload["message"] != "之前暂存的委托修改已经补交成功。" {
				t.Errorf("unexpected notice message: %v", wsMsg.Payload["message"])
			}
		default:
			t.Errorf("session %s did not receive the broadcast notice", session.ID)
		}
	}
}

func TestUserFocusStatus_RepliesCurrentStateToRequestingSession(t *testing.T) {
	b, _ := newTestNatsBridge(t)
	focus := engine.NewFocusManager(zap.NewNop())
	b.SetFocusManager(focus)

	const chatID = int64(8104)
	focus.Start(chatID, 30)

	session := newFocusTestSession(chatID)
	b.HandleUserWSMessage(session, websocket.MessageText, []byte(`{"type":"user.focus_status"}`))

	select {
	case frame := <-session.sendChan:
		var wsMsg struct {
			Type    string            `json:"type"`
			Payload engine.FocusState `json:"payload"`
		}
		if err := json.Unmarshal(frame.Data, &wsMsg); err != nil {
			t.Fatalf("failed to unmarshal focus state frame: %v", err)
		}
		if wsMsg.Type != "agent.focus_state" {
			t.Fatalf("expected agent.focus_state frame, got %s", wsMsg.Type)
		}
		if wsMsg.Payload.Phase != engine.FocusPhaseRunning || wsMsg.Payload.PlannedMinutes != 30 {
			t.Fatalf("unexpected focus state payload: %+v", wsMsg.Payload)
		}
	default:
		t.Fatalf("expected a focus state reply frame")
	}
}
