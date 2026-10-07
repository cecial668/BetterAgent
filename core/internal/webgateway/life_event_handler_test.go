package webgateway

import (
	"bytes"
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"

	"go.uber.org/zap"

	"betteragent-core/internal/engine"
)

func newTestLifeEventServer(token string) *Server {
	return &Server{
		lifeEventToken: token,
		gameEventWeights: GameEventWeights{
			DefaultWeight: 0.1,
			Games: map[string]map[string]float64{
				"life": {
					"morning_brief":       0.8,
					"required_unfinished": 1.1,
				},
			},
		},
		urgeEngine: engine.NewUrgeEngine(engine.UrgeParams{UrgeCap: 100}, zap.NewNop()),
		logger:     zap.NewNop(),
	}
}

func postLifeEvent(s *Server, token string, body string) *httptest.ResponseRecorder {
	req := httptest.NewRequest("POST", "/api/life-event", bytes.NewBufferString(body))
	if token != "" {
		req.Header.Set("X-Life-Event-Token", token)
	}
	rec := httptest.NewRecorder()
	s.handleLifeEvent(rec, req)
	return rec
}

func TestHandleLifeEvent_MissingConfiguredToken_Returns503(t *testing.T) {
	s := newTestLifeEventServer("")
	rec := postLifeEvent(s, "", `{"event_type":"morning_brief"}`)
	if rec.Code != 503 {
		t.Errorf("expected 503 when LIFE_EVENT_TOKEN is unset, got %d", rec.Code)
	}
}

func TestHandleLifeEvent_GameTokenDoesNotOpenLifeEndpoint(t *testing.T) {
	// Token independence: a valid GAME_EVENT_TOKEN must not authorize the
	// life endpoint (and vice versa) -- separate trust boundaries.
	s := newTestLifeEventServer("")
	req := httptest.NewRequest("POST", "/api/life-event", bytes.NewBufferString(`{"event_type":"morning_brief"}`))
	req.Header.Set("X-Game-Event-Token", "correct-game-token")
	rec := httptest.NewRecorder()
	s.handleLifeEvent(rec, req)
	if rec.Code != 503 {
		t.Errorf("expected 503 (life token unset) even with a game token, got %d", rec.Code)
	}
}

func TestHandleLifeEvent_BadToken_Returns401BeforeBodyRead(t *testing.T) {
	s := newTestLifeEventServer("correct-token")
	rec := postLifeEvent(s, "wrong-token", `{"event_type":"morning_brief"}`)
	if rec.Code != 401 {
		t.Errorf("expected 401 for invalid token, got %d", rec.Code)
	}
	if s.urgeEngine.CurrentValue() != 0 {
		t.Errorf("expected no Urge side effect for a rejected request, got %f", s.urgeEngine.CurrentValue())
	}
}

func TestHandleLifeEvent_OversizedBody_Returns413(t *testing.T) {
	s := newTestLifeEventServer("correct-token")
	huge := strings.Repeat("a", lifeEventMaxBodyBytes+1)
	rec := postLifeEvent(s, "correct-token", `{"event_type":"morning_brief","detail":"`+huge+`"}`)
	if rec.Code != 413 {
		t.Errorf("expected 413 for oversized body, got %d", rec.Code)
	}
}

func TestHandleLifeEvent_InvalidJSON_Returns400(t *testing.T) {
	s := newTestLifeEventServer("correct-token")
	rec := postLifeEvent(s, "correct-token", `not json`)
	if rec.Code != 400 {
		t.Errorf("expected 400 for invalid JSON, got %d", rec.Code)
	}
}

func TestHandleLifeEvent_InvalidEventTypeCharset_Returns400(t *testing.T) {
	s := newTestLifeEventServer("correct-token")
	rec := postLifeEvent(s, "correct-token", `{"event_type":"Morning Brief!"}`)
	if rec.Code != 400 {
		t.Errorf("expected 400 for event_type outside ^[a-z0-9_]{1,64}$, got %d", rec.Code)
	}
}

func TestHandleLifeEvent_ValidRequest_UsesConfigWeightNotClientSupplied(t *testing.T) {
	s := newTestLifeEventServer("correct-token")
	rec := postLifeEvent(s, "correct-token", `{"event_type":"required_unfinished","weight":999,"detail":"还差 2 条必要委托"}`)
	if rec.Code != 200 {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}

	var resp map[string]interface{}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}
	if resp["urge_added"] != 1.1 {
		t.Errorf("expected urge_added=1.1 (config-resolved), got %v", resp["urge_added"])
	}
}

func TestHandleLifeEvent_UnknownEventType_FallsBackToDefaultWeight(t *testing.T) {
	s := newTestLifeEventServer("correct-token")
	rec := postLifeEvent(s, "correct-token", `{"event_type":"some_new_future_event"}`)
	if rec.Code != 200 {
		t.Fatalf("expected 200 for unknown event_type (should fall back, not reject), got %d: %s", rec.Code, rec.Body.String())
	}
	var resp map[string]interface{}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}
	if resp["urge_added"] != 0.1 {
		t.Errorf("expected fallback to default_weight=0.1, got %v", resp["urge_added"])
	}
}

func TestHandleLifeEvent_WrongMethod_Returns405(t *testing.T) {
	s := newTestLifeEventServer("correct-token")
	req := httptest.NewRequest("GET", "/api/life-event", nil)
	req.Header.Set("X-Life-Event-Token", "correct-token")
	rec := httptest.NewRecorder()
	s.handleLifeEvent(rec, req)
	if rec.Code != 405 {
		t.Errorf("expected 405 for GET, got %d", rec.Code)
	}
}
