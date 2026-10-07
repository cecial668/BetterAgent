package engine

import (
	"math"
	"sync"
	"time"

	"go.uber.org/zap"

	"betteragent-core/internal/emotion"
)

// UrgeParams configures UrgeEngine's accumulation/threshold/cooldown
// behavior. All duration fields are already resolved from config seconds by
// the caller (see cmd/main.go).
type UrgeParams struct {
	AlphaBoredom         float64
	BetaGameEvent        float64
	GammaUnreadPressure  float64
	BaseThreshold        float64
	ArousalSensitivity   float64
	EnergyPenalty        float64
	MinThreshold         float64
	MaxThreshold         float64
	UrgeCap              float64
	CooldownDuration     time.Duration
	DeadZoneDuration     time.Duration
	GameEventDecay       time.Duration
	UnreadPressureWindow time.Duration
	PrimaryChatID        int64
	TargetSessionMaxAge  time.Duration

	// 用户配置的主动策略（config.yaml 的 integration.tothestars.proactive，
	// 即设置页「生活数据 → 主动提及策略」）：静默时段 + 频率上限。
	// 频率上限按"实际开口次数"计（含无聊搭话与生活事件触发的主动），
	// 0 = 不限制；静默时段可跨零点（如 23:00 → 07:00）。
	QuietHoursEnabled   bool
	QuietStartMinute    int
	QuietEndMinute      int
	MaxProactivePerHour int
	MaxProactivePerDay  int
}

const defaultProactiveReason = "一段时间没有人跟你说话，你觉得有点无聊，想主动搭个话"

// UrgeEngine accumulates a global "urge to speak" impulse, integrated once
// per ClockEngine tick from boredom + decaying game-event spikes + a proxy
// for unread-chat pressure, and fires a proactive turn once the accumulator
// crosses a mood-dependent dynamic threshold. A single global accumulator
// mirrors the existing global EmotionalState singleton (see
// docs/ARCHITECTURE.md) -- the catgirl has one "want to talk" impulse, not
// one per chat.
type UrgeEngine struct {
	mu sync.Mutex

	params UrgeParams

	value                float64
	gameEventEnergy      float64
	cooldownUntil        time.Time
	deadZoneUntil        time.Time
	consecutiveUnreplied int
	lastReason           string
	// proactiveFireTimes 记录每次真正开口主动说话的时间戳，用于"每小时/每天
	// 最多主动几次"的频率上限（见 integration.tothestars.proactive）。
	proactiveFireTimes []time.Time

	logger *zap.Logger
}

func NewUrgeEngine(params UrgeParams, logger *zap.Logger) *UrgeEngine {
	return &UrgeEngine{
		params: params,
		logger: logger,
	}
}

// CurrentValue returns a snapshot of the current Urge accumulator, mainly
// for diagnostic responses (see webgateway/game_event_handler.go).
func (u *UrgeEngine) CurrentValue() float64 {
	u.mu.Lock()
	defer u.mu.Unlock()
	return u.value
}

func (u *UrgeEngine) PrimaryChatID() int64                { return u.params.PrimaryChatID }
func (u *UrgeEngine) TargetMaxAge() time.Duration         { return u.params.TargetSessionMaxAge }
func (u *UrgeEngine) UnreadPressureWindow() time.Duration { return u.params.UnreadPressureWindow }

// RecordGameEvent adds weight to the decaying "hot" game-event contribution
// and remembers reason as the proactive-reason text to use if this spike is
// what pushes Urge over threshold. Called in-process by the game-event HTTP
// handler -- not round-tripped through NATS, so it stays correct even if the
// bus is offline.
func (u *UrgeEngine) RecordGameEvent(weight float64, reason string) {
	u.mu.Lock()
	defer u.mu.Unlock()
	u.gameEventEnergy += weight
	if reason != "" {
		u.lastReason = reason
	}
	u.logger.Debug("UrgeEngine recorded game event",
		zap.Float64("weight", weight),
		zap.Float64("game_event_energy", u.gameEventEnergy),
	)
}

// OnUserActivity resets the consecutive unreplied proactive counter when the
// user interacts/sends a message, returning proactive threshold to normal.
func (u *UrgeEngine) OnUserActivity() {
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.consecutiveUnreplied > 0 {
		u.logger.Info("UrgeEngine: User activity received, resetting consecutive unreplied counter to 0",
			zap.Int("previous_unreplied", u.consecutiveUnreplied),
		)
		u.consecutiveUnreplied = 0
	}
}

// ConsecutiveUnreplied returns current unreplied proactive count (diagnostic/test).
func (u *UrgeEngine) ConsecutiveUnreplied() int {
	u.mu.Lock()
	defer u.mu.Unlock()
	return u.consecutiveUnreplied
}

// OnTurnCompleted resets Urge to zero and enforces the cooldown/dead-zone
// refractory period. Called on every completed turn (proactive or not) so
// the catgirl never becomes a repeat-chatterbox regardless of what
// triggered the turn that just finished.
func (u *UrgeEngine) OnTurnCompleted() {
	u.mu.Lock()
	defer u.mu.Unlock()
	now := time.Now()
	u.value = 0
	u.gameEventEnergy = 0
	u.lastReason = ""
	if u.params.CooldownDuration > 0 {
		u.cooldownUntil = now.Add(u.params.CooldownDuration)
	}
	if u.params.DeadZoneDuration > 0 {
		u.deadZoneUntil = now.Add(u.params.DeadZoneDuration)
	}
}

// minuteOfDay converts a wall-clock time to minutes since midnight (0..1439).
func minuteOfDay(t time.Time) int { return t.Hour()*60 + t.Minute() }

// inQuietHours reports whether now falls inside the user-configured quiet
// window. A start == end window is treated as "no quiet hours". Windows may
// cross midnight (e.g. 23:00 -> 07:00), matching the settings page.
func (u *UrgeEngine) inQuietHours(now time.Time) bool {
	if !u.params.QuietHoursEnabled || u.params.QuietStartMinute == u.params.QuietEndMinute {
		return false
	}
	start, end := u.params.QuietStartMinute, u.params.QuietEndMinute
	current := minuteOfDay(now)
	if start < end {
		return current >= start && current < end
	}
	return current >= start || current < end
}

// withinFrequencyCaps prunes fire history older than 24h and reports whether
// the configured hourly/daily proactive-message caps still allow a turn now.
// 0 means unlimited; caps count actual proactive turns (boredom chatter and
// life events alike), so any one channel can't exhaust the day's budget alone.
func (u *UrgeEngine) withinFrequencyCaps(now time.Time) bool {
	cutoff := now.Add(-24 * time.Hour)
	kept := u.proactiveFireTimes[:0]
	for _, firedAt := range u.proactiveFireTimes {
		if firedAt.After(cutoff) {
			kept = append(kept, firedAt)
		}
	}
	u.proactiveFireTimes = kept

	if u.params.MaxProactivePerDay > 0 && len(u.proactiveFireTimes) >= u.params.MaxProactivePerDay {
		return false
	}
	if u.params.MaxProactivePerHour > 0 {
		hourCutoff := now.Add(-time.Hour)
		recent := 0
		for _, firedAt := range u.proactiveFireTimes {
			if firedAt.After(hourCutoff) {
				recent++
			}
		}
		if recent >= u.params.MaxProactivePerHour {
			return false
		}
	}
	return true
}

// EvaluateTick integrates one tick's worth of Urge and decides whether to
// fire a proactive turn. Must be called after emotionalState.ApplyTimeDecay
// and stateMachine.EvaluateTick so it reads post-decay mood and
// post-transition FSM state.
func (u *UrgeEngine) EvaluateTick(
	now time.Time,
	elapsed time.Duration,
	emoState *emotion.EmotionalState,
	personality *emotion.PersonalityProfile,
	isSleepHours bool,
	targetState State,
	unreadPressure int,
) (shouldFire bool, reason string) {
	u.mu.Lock()
	defer u.mu.Unlock()

	elapsedSeconds := elapsed.Seconds()
	if elapsedSeconds < 0 {
		elapsedSeconds = 0
	}

	// 1. Decay the "hot" game-event contribution first.
	if u.params.GameEventDecay > 0 && u.gameEventEnergy != 0 {
		decayFactor := math.Exp(-elapsedSeconds / u.params.GameEventDecay.Seconds())
		u.gameEventEnergy *= decayFactor
	}

	// 2. Boredom term -- Extraversion is the existing PersonalityProfile
	// field documented as "high = proactive"; this is the first place it
	// actually does anything.
	extraversion := 0.5
	if personality != nil {
		extraversion = personality.Extraversion
	}
	boredomRate := 0.6 + 0.4*extraversion

	// 3. Integrate.
	integrand := u.params.AlphaBoredom*boredomRate +
		u.params.BetaGameEvent*u.gameEventEnergy +
		u.params.GammaUnreadPressure*float64(unreadPressure)
	u.value += integrand * elapsedSeconds
	u.value = clamp(u.value, 0, u.params.UrgeCap)

	// 4. Hard gates -- never interrupt an ongoing turn, speak during sleep
	// hours, or fire again inside the post-speech cooldown/dead-zone.
	// cooldownUntil is the longer refractory window (config: cooldown_seconds,
	// e.g. 90s); deadZoneUntil is the short one (dead_zone_seconds, e.g. 20s)
	// -- both are set together by OnTurnCompleted, so both must be checked
	// here or the shorter one silently wins regardless of how the longer one
	// is configured.
	if now.Before(u.cooldownUntil) || now.Before(u.deadZoneUntil) || isSleepHours || targetState != StateIdle {
		return false, ""
	}

	// 4.5 用户策略硬门：静默时段 × 频率上限（来自设置页；与心情、冷却、
	// 状态机同为「与」关系，任何一个不允许就不开口）。
	if u.inQuietHours(now) || !u.withinFrequencyCaps(now) {
		return false, ""
	}

	// 5. Dynamic threshold from mood: high arousal lowers it (talks more),
	// low energy raises it (talks less).
	arousal, energy := 0.5, 0.5
	if emoState != nil {
		arousal = emoState.GetArousal()
		energy = emoState.GetEnergy()
	}
	threshold := u.params.BaseThreshold *
		(1 - u.params.ArousalSensitivity*(arousal-0.5)) *
		(1 + u.params.EnergyPenalty*(1-energy))

	// 6. Exponential backoff for unreplied proactive turns:
	// If master does not reply to proactive chatter(s), scale threshold up
	// (1.0x -> 1.8x -> 3.24x -> 5.0x cap), reducing proactive chatter frequency.
	if u.consecutiveUnreplied > 0 {
		backoffFactor := math.Pow(1.8, float64(u.consecutiveUnreplied))
		if backoffFactor > 5.0 {
			backoffFactor = 5.0
		}
		threshold *= backoffFactor
	}

	threshold = clamp(threshold, u.params.MinThreshold, u.params.MaxThreshold*5.0)

	if u.value < threshold {
		return false, ""
	}

	reason = u.lastReason
	if reason == "" {
		reason = defaultProactiveReason
	}
	u.value = 0
	u.gameEventEnergy = 0
	u.lastReason = ""
	u.consecutiveUnreplied++
	u.proactiveFireTimes = append(u.proactiveFireTimes, now)
	u.logger.Info("UrgeEngine proactive turn triggered",
		zap.Int("consecutive_unreplied", u.consecutiveUnreplied),
		zap.String("reason", reason),
	)
	return true, reason
}

func clamp(v, min, max float64) float64 {
	if v < min {
		return min
	}
	if v > max {
		return max
	}
	return v
}

// ResolveProactiveTarget picks which chat a proactive turn should be aimed
// at: a pinned primaryChatID if configured, otherwise the most recently
// active chat (within maxAge), otherwise none.
func ResolveProactiveTarget(csm *CentralStateMachine, primaryChatID int64, maxAge time.Duration) (int64, bool) {
	if primaryChatID != 0 {
		return primaryChatID, true
	}
	return csm.GetMostRecentlyActiveChatID(maxAge)
}
