package webgateway

import (
	"encoding/json"
	"strings"
	"testing"

	"nhooyr.io/websocket"

	"betteragent-core/internal/engine"
)

func greetingFrame(t *testing.T, awaySeconds *int64) []byte {
	t.Helper()
	var payload json.RawMessage
	if awaySeconds != nil {
		marshaled, err := json.Marshal(UserGreetingPayload{AwaySeconds: awaySeconds})
		if err != nil {
			t.Fatalf("failed to marshal greeting payload: %v", err)
		}
		payload = marshaled
	}
	data, err := json.Marshal(WSMessage{Type: "user.greeting", Payload: payload})
	if err != nil {
		t.Fatalf("failed to marshal greeting frame: %v", err)
	}
	return data
}

func newGreetingTestSession(chatID int64) *ClientSession {
	return &ClientSession{ID: "greeting-test-session", ChatID: chatID}
}

func TestHandleUserGreeting_StartsProactiveTurn(t *testing.T) {
	b, _ := newTestNatsBridge(t)
	away := int64(2 * 3600)

	b.HandleUserWSMessage(newGreetingTestSession(7101), websocket.MessageText, greetingFrame(t, &away))

	if got := b.csm.GetChatState(7101); got != engine.StateThinking {
		t.Errorf("expected a page-open greeting to start a proactive turn (THINKING), got %s", got)
	}
}

func TestHandleUserGreeting_BareFrameWithoutPayloadStillGreets(t *testing.T) {
	b, _ := newTestNatsBridge(t)

	// First-ever visit: the frontend has no "away since" to report and sends
	// an empty payload -- that must still be a valid greeting trigger.
	b.HandleUserWSMessage(newGreetingTestSession(7105), websocket.MessageText, greetingFrame(t, nil))

	if got := b.csm.GetChatState(7105); got != engine.StateThinking {
		t.Errorf("expected a bare page-open frame to start a greeting turn, got %s", got)
	}
}

func TestHandleUserGreeting_CooldownSuppressesSecondPageOpen(t *testing.T) {
	b, _ := newTestNatsBridge(t)
	session := newGreetingTestSession(7102)

	b.HandleUserWSMessage(session, websocket.MessageText, greetingFrame(t, nil))
	// Simulate the greeting turn finishing, then a quick second page open
	// (an F5 or a second tab) -- the cooldown must absorb it.
	b.csm.TransitionToChat(7102, engine.StateIdle, "test: greeting turn finished")
	b.HandleUserWSMessage(session, websocket.MessageText, greetingFrame(t, nil))

	if got := b.csm.GetChatState(7102); got != engine.StateIdle {
		t.Errorf("expected the second greeting inside the cooldown to be ignored (state stays IDLE), got %s", got)
	}
}

func TestHandleUserGreeting_SkipsWhenTurnInProgress(t *testing.T) {
	b, _ := newTestNatsBridge(t)
	session := newGreetingTestSession(7103)
	// IDLE cannot jump straight to TALKING (see IsValidTransition); walk the
	// real path so the test truly exercises "a turn is already running".
	b.csm.TransitionToChat(7103, engine.StateThinking, "test: turn started")
	b.csm.TransitionToChat(7103, engine.StateTalking, "test: mid-turn")

	b.HandleUserWSMessage(session, websocket.MessageText, greetingFrame(t, nil))

	if got := b.csm.GetChatState(7103); got != engine.StateTalking {
		t.Errorf("expected a mid-turn page open to leave the running turn untouched (TALKING), got %s", got)
	}
}

func TestHandleUserGreeting_AllowsRestingStates(t *testing.T) {
	b, _ := newTestNatsBridge(t)
	session := newGreetingTestSession(7104)
	b.csm.TransitionToChat(7104, engine.StateSleeping, "test: sleepy")

	b.HandleUserWSMessage(session, websocket.MessageText, greetingFrame(t, nil))

	// A sleeping 芙宁娜 opening her eyes to greet is exactly the charm case;
	// SLEEPING -> THINKING is a valid transition (see IsValidTransition).
	if got := b.csm.GetChatState(7104); got != engine.StateThinking {
		t.Errorf("expected greeting to wake a SLEEPING chat into THINKING, got %s", got)
	}
}

func TestBuildGreetingReason_IncludesAwayDurationAndAngleHint(t *testing.T) {
	away := int64(2 * 3600)
	reason := buildGreetingReason(&away)

	if !strings.Contains(reason, "打个招呼") {
		t.Errorf("expected reason to describe a greeting, got: %s", reason)
	}
	if !strings.Contains(reason, "2 小时") {
		t.Errorf("expected reason to mention the 2h away duration, got: %s", reason)
	}
	if !strings.Contains(reason, "角度") {
		t.Errorf("expected reason to carry a random angle hint, got: %s", reason)
	}
}

func TestFormatAwayDuration(t *testing.T) {
	cases := []struct {
		seconds int64
		want    string
	}{
		{seconds: 10, want: "一小会儿"},
		{seconds: 90, want: "1 分钟"},
		{seconds: 3 * 3600, want: "3 小时"},
		{seconds: 2 * 86400, want: "2 天"},
		{seconds: 45 * 86400, want: "一个多月"},
	}
	for _, c := range cases {
		if got := formatAwayDuration(c.seconds); got != c.want {
			t.Errorf("formatAwayDuration(%d) = %q, want %q", c.seconds, got, c.want)
		}
	}
}
