package webgateway

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"

	"go.uber.org/zap"

	"betteragent-core/internal/bus"
	"betteragent-core/internal/schema"
)

// 生活事件（向着星 Life Bridge）的摄入入口。
//
// 形态与 /api/game-event 一致：token 校验 + 服务端解析权重 + 喂
// UrgeEngine.RecordGameEvent。差别只在两处：
//   - 独立 token（LIFE_EVENT_TOKEN）：生活数据桥与游戏观察者是两条独立的
//     信任边界，任何一条 token 泄漏都不应影响另一条（见 docs/SECURITY.md）；
//   - 事件类别固定为 "life"，权重从 game_events.games.life 读取，客户端
//     永远不能自带权重。
//
// 静默时段与频率上限不在这里判断：它们落在 UrgeEngine.EvaluateTick 的硬门里
// （见 urge_engine.go），这样无论冲动来自生活事件、无聊累积还是游戏事件，
// 都受同一套用户策略约束 —— 同一时间只可能有一条"要不要开口"的判定路径。
const lifeEventMaxBodyBytes = 8 * 1024
const lifeEventDetailMaxLen = 500

var lifeEventNamePattern = regexp.MustCompile(`^[a-z0-9_]{1,64}$`)

type lifeEventRequest struct {
	EventType string                 `json:"event_type"`
	Detail    string                 `json:"detail,omitempty"`
	Metadata  map[string]interface{} `json:"metadata,omitempty"`
}

// handleLifeEvent is POST /api/life-event, served on the same dedicated
// loopback-only listener as /api/game-event (core_engine.game_event_bind_addr).
func (s *Server) handleLifeEvent(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Optional integration: an unset token disables the endpoint instead of
	// failing core startup (same posture as the game-event endpoint).
	if s.lifeEventToken == "" {
		writeGameEventJSON(w, http.StatusServiceUnavailable, map[string]interface{}{"error": "life event ingestion disabled"})
		return
	}

	suppliedToken := r.Header.Get("X-Life-Event-Token")
	if subtle.ConstantTimeCompare([]byte(suppliedToken), []byte(s.lifeEventToken)) != 1 {
		s.logger.Warn("Rejected life event with invalid/missing token", zap.String("remote_addr", r.RemoteAddr))
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, lifeEventMaxBodyBytes)
	var req lifeEventRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		var maxBytesErr *http.MaxBytesError
		if errors.As(err, &maxBytesErr) {
			http.Error(w, `{"error":"request body too large"}`, http.StatusRequestEntityTooLarge)
			return
		}
		http.Error(w, `{"error":"invalid JSON body"}`, http.StatusBadRequest)
		return
	}

	if !lifeEventNamePattern.MatchString(req.EventType) {
		http.Error(w, `{"error":"event_type must match ^[a-z0-9_]{1,64}$"}`, http.StatusBadRequest)
		return
	}

	if len(req.Detail) > lifeEventDetailMaxLen {
		req.Detail = req.Detail[:lifeEventDetailMaxLen]
	}

	weight := s.gameEventWeights.lookup("life", req.EventType)

	var currentUrge float64
	if s.urgeEngine != nil {
		s.urgeEngine.RecordGameEvent(weight, req.Detail)
		currentUrge = s.urgeEngine.CurrentValue()
	}

	s.logger.Info("🌟 Life event received",
		zap.String("event_type", req.EventType),
		zap.Float64("weight", weight),
	)

	// Observability only: UrgeEngine above is the real side effect. Publish
	// under the same subject as game events (game="life") so any future
	// consumer sees one unified event stream.
	if s.bridge != nil && s.bridge.bus != nil {
		var detailPtr *string
		if req.Detail != "" {
			detailPtr = &req.Detail
		}
		payload := schema.GameEventPayload{
			BasePayload: schema.NewBasePayload("webgateway_life_event"),
			Game:        "life",
			EventType:   req.EventType,
			Weight:      weight,
			Detail:      detailPtr,
			Metadata:    req.Metadata,
		}
		if err := s.bridge.bus.Publish(bus.SubjectGameEvent, "webgateway_life_event", payload); err != nil {
			s.logger.Error("Failed to publish LifeEvent to NATS", zap.Error(err))
		}
	}

	writeGameEventJSON(w, http.StatusOK, map[string]interface{}{
		"status":       "ok",
		"urge_added":   weight,
		"current_urge": currentUrge,
	})
}
