package webgateway

import (
	"testing"

	"go.uber.org/zap"
)

// 同一 chat 多页面连接时，音频只发给"最后发言"的那个会话；
// 没有活跃记录 / 活跃会话下线时回退为广播（单窗口场景行为不变）。
func TestSessionManager_BinaryTargetsLastActiveSession(t *testing.T) {
	logger := zap.NewNop()
	m := newSessionManager(logger)
	a := newClientSession(1001, nil, logger)
	b := newClientSession(1001, nil, logger)
	m.Register(a)
	m.Register(b)

	// 未标记活跃：回退广播给同 chat 的所有会话（旧行为）
	m.SendBinaryToChat(1001, []byte{0})
	if len(a.sendChan) != 1 || len(b.sendChan) != 1 {
		t.Fatalf("expected fallback broadcast without active session, got a=%d b=%d", len(a.sendChan), len(b.sendChan))
	}

	// a 发言后：音频只进 a，b 保持安静 —— 这就是"叠唱二重奏"的服务端修复
	m.MarkActive(1001, a.ID)
	m.SendBinaryToChat(1001, []byte{1})
	if len(a.sendChan) != 2 {
		t.Errorf("expected active session a to receive audio, got %d frames", len(a.sendChan))
	}
	if len(b.sendChan) != 1 {
		t.Errorf("expected non-active session b to stay silent, got %d frames", len(b.sendChan))
	}

	// 换 b 发言后，音频跟着切到 b
	m.MarkActive(1001, b.ID)
	m.SendBinaryToChat(1001, []byte{2})
	if len(b.sendChan) != 2 {
		t.Errorf("expected audio to follow the latest speaker (b), got %d frames", len(b.sendChan))
	}
	if len(a.sendChan) != 2 {
		t.Errorf("expected a to go quiet after b spoke, got %d frames", len(a.sendChan))
	}

	// 其它 chat 不受影响
	m.SendBinaryToChat(2002, []byte{3})
	if len(a.sendChan) != 2 || len(b.sendChan) != 2 {
		t.Errorf("expected unrelated chat to receive nothing, got a=%d b=%d", len(a.sendChan), len(b.sendChan))
	}

	// 活跃会话下线：回退广播，剩下的页面照常能听到
	m.Unregister(b)
	m.SendBinaryToChat(1001, []byte{4})
	if len(a.sendChan) != 3 {
		t.Errorf("expected fallback broadcast after active session unregistered, got a=%d", len(a.sendChan))
	}
}
