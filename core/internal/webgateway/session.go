package webgateway

import (
	"context"
	"sync"
	"sync/atomic"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"
	"nhooyr.io/websocket"
)

const writeWait = 10 * time.Second

type WSFrame struct {
	MessageType websocket.MessageType
	Data        []byte
}

type ClientSession struct {
	ID           string
	ChatID       int64
	generationID uint64
	conn         *websocket.Conn
	sendChan     chan WSFrame
	logger       *zap.Logger
	ctx          context.Context
	cancel       context.CancelFunc
}

func newClientSession(chatID int64, conn *websocket.Conn, logger *zap.Logger) *ClientSession {
	ctx, cancel := context.WithCancel(context.Background())
	return &ClientSession{
		ID:           uuid.New().String(),
		ChatID:       chatID,
		generationID: 1,
		conn:         conn,
		sendChan:     make(chan WSFrame, 256),
		logger:       logger,
		ctx:          ctx,
		cancel:       cancel,
	}
}

func (s *ClientSession) GetGenerationID() uint64 {
	return atomic.LoadUint64(&s.generationID)
}

func (s *ClientSession) IncrementGeneration() uint64 {
	return atomic.AddUint64(&s.generationID, 1)
}

func (s *ClientSession) ClearSendBuffer() {
	s.IncrementGeneration()
	drained := 0
	for len(s.sendChan) > 0 {
		select {
		case <-s.sendChan:
			drained++
		default:
		}
	}
	if drained > 0 {
		s.logger.Info("Cleared queued audio/text buffer on user interrupt",
			zap.String("session_id", s.ID),
			zap.Int64("chat_id", s.ChatID),
			zap.Int("drained_frames", drained),
		)
	}
}

func (s *ClientSession) SendText(data []byte) {
	s.SendFrame(WSFrame{
		MessageType: websocket.MessageText,
		Data:        data,
	})
}

func (s *ClientSession) SendBinary(data []byte) {
	s.SendFrame(WSFrame{
		MessageType: websocket.MessageBinary,
		Data:        data,
	})
}

func (s *ClientSession) SendFrame(frame WSFrame) {
	select {
	case s.sendChan <- frame:
	default:
		s.logger.Warn("Session write buffer full, dropping frame", zap.String("session_id", s.ID))
	}
}

func (s *ClientSession) writeLoop() {
	defer func() {
		s.conn.Close(websocket.StatusNormalClosure, "session closed")
	}()

	for {
		select {
		case <-s.ctx.Done():
			return
		case frame, ok := <-s.sendChan:
			if !ok {
				return
			}
			ctx, cancel := context.WithTimeout(s.ctx, writeWait)
			err := s.conn.Write(ctx, frame.MessageType, frame.Data)
			cancel()
			if err != nil {
				s.logger.Error("Failed to write to WebSocket", zap.String("session_id", s.ID), zap.Error(err))
				return
			}
		}
	}
}

type SessionManager struct {
	mu       sync.RWMutex
	sessions map[string]*ClientSession
	// latestActive 记录每个 chat 最近一次「用户发言」来自哪个会话。同一 chat
	// 可能同时连着多个页面（数字人舞台开了两个标签页、或舞台+其他窗口都连着
	// 同一个 chat_id）；若把音频广播给所有会话，同一句语音会被两个页面各自
	// 播放一次，听感就是"同一句话叠唱两遍"。音频只发给最后发言的页面，语义上
	// 也说得通：她回应的是你正在说话的那个屏幕。
	latestActive map[int64]string
	logger       *zap.Logger
}

func newSessionManager(logger *zap.Logger) *SessionManager {
	return &SessionManager{
		sessions:     make(map[string]*ClientSession),
		latestActive: make(map[int64]string),
		logger:       logger,
	}
}

func (m *SessionManager) Register(s *ClientSession) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.sessions[s.ID] = s
	m.logger.Info("WebGateway Client Session Registered", zap.String("session_id", s.ID), zap.Int64("chat_id", s.ChatID))
}

func (m *SessionManager) Unregister(s *ClientSession) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.sessions[s.ID]; ok {
		delete(m.sessions, s.ID)
		if m.latestActive[s.ChatID] == s.ID {
			delete(m.latestActive, s.ChatID)
		}
		s.cancel()
		m.logger.Info("WebGateway Client Session Unregistered", zap.String("session_id", s.ID))
	}
}

// MarkActive remembers which session most recently spoke for a chat. Called on
// inbound user text / VAD speech start, i.e. actual user activity -- NOT on
// connection registration, so merely opening a second page (e.g. settings)
// can never steal audio away from the window the user is actually talking to.
func (m *SessionManager) MarkActive(chatID int64, sessionID string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.latestActive[chatID] != sessionID {
		m.latestActive[chatID] = sessionID
		m.logger.Info("WebGateway active session for chat updated",
			zap.Int64("chat_id", chatID), zap.String("session_id", sessionID))
	}
}

func (m *SessionManager) ClearChatBuffers(chatID int64) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	for _, s := range m.sessions {
		if s.ChatID == chatID {
			s.ClearSendBuffer()
		}
	}
}

func (m *SessionManager) SendTextToChat(chatID int64, data []byte) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	for _, s := range m.sessions {
		if s.ChatID == chatID {
			s.SendText(data)
		}
	}
}

// BroadcastText delivers a text frame to every connected session regardless
// of chat. Used only for UI-only notices that are not chat-scoped (e.g. a
// queued 向着星 write finally delivered) -- never for dialogue.
func (m *SessionManager) BroadcastText(data []byte) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	for _, s := range m.sessions {
		s.SendText(data)
	}
}

// SendBinaryToChat delivers audio frames to at most ONE session per chat --
// the last one the user actually spoke from (see latestActive). Falls back to
// every matching session when no activity has been recorded yet, preserving
// the old behaviour for single-window setups.
func (m *SessionManager) SendBinaryToChat(chatID int64, data []byte) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if activeID, ok := m.latestActive[chatID]; ok {
		if active, exists := m.sessions[activeID]; exists && active.ChatID == chatID {
			active.SendBinary(data)
			return
		}
	}
	for _, s := range m.sessions {
		if s.ChatID == chatID {
			s.SendBinary(data)
		}
	}
}
