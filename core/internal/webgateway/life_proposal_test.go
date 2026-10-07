package webgateway

import (
	"encoding/json"
	"testing"

	"github.com/nats-io/nats.go"
	"go.uber.org/zap"
)

func TestHandleLifeProposalMsg_IgnoresMalformedWithoutPanic(t *testing.T) {
	logger := zap.NewNop()
	b := &NatsBridge{sessions: newSessionManager(logger), logger: logger}

	// 坏 JSON / 缺 chat_id / 缺 proposal_id 一律安静丢弃：
	// 确认框事件是可选增强，坏帧绝不能拖垮 WebGateway 的 NATS 回调。
	cases := []string{
		`not json`,
		`{}`,
		`{"payload":{"proposal_id":"abc","phase":"pending"}}`,
		`{"payload":{"chat_id":123,"phase":"pending"}}`,
	}
	for _, raw := range cases {
		b.handleLifeProposalMsg(&nats.Msg{Data: []byte(raw)})
	}
}

func TestLifeProposalWSFrame_MarshalShape(t *testing.T) {
	frame := WSMessage{
		Type: "agent.life_proposal",
		Payload: marshalRaw(AgentLifeProposalPayload{
			ChatID:     9000000000001001,
			ProposalID: "abc123def456",
			Phase:      "pending",
			Kind:       "commission.create",
			Params:     map[string]interface{}{"title": "取快递"},
			Summary:    "新增委托「取快递」",
		}),
	}

	raw, err := json.Marshal(frame)
	if err != nil {
		t.Fatalf("failed to marshal life proposal frame: %v", err)
	}

	var decoded struct {
		Type    string                    `json:"type"`
		Payload AgentLifeProposalPayload  `json:"payload"`
	}
	if err := json.Unmarshal(raw, &decoded); err != nil {
		t.Fatalf("failed to unmarshal life proposal frame: %v", err)
	}
	if decoded.Type != "agent.life_proposal" {
		t.Errorf("expected type agent.life_proposal, got %q", decoded.Type)
	}
	if decoded.Payload.ProposalID != "abc123def456" || decoded.Payload.Phase != "pending" {
		t.Errorf("payload mismatch: %+v", decoded.Payload)
	}
	if decoded.Payload.Params["title"] != "取快递" {
		t.Errorf("params not round-tripped: %+v", decoded.Payload.Params)
	}
}
