package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"go.uber.org/zap"

	"betteragent-core/internal/bus"
	"betteragent-core/internal/config"
	"betteragent-core/internal/emotion"
	"betteragent-core/internal/engine"
	"betteragent-core/internal/gotd"
	"betteragent-core/internal/webgateway"
)

// parseQuietHours converts ["23:00", "07:00"] into minute offsets. Returns
// ok=false (quiet hours disabled) for missing/malformed values so a typo in
// config.yaml degrades to "no quiet window" instead of silencing her forever.
func parseQuietHours(values []string) (startMinute, endMinute int, ok bool) {
	if len(values) != 2 {
		return 0, 0, false
	}
	parse := func(raw string) (int, bool) {
		parts := strings.Split(strings.TrimSpace(raw), ":")
		if len(parts) != 2 {
			return 0, false
		}
		hour, errH := strconv.Atoi(parts[0])
		minute, errM := strconv.Atoi(parts[1])
		if errH != nil || errM != nil || hour < 0 || hour > 23 || minute < 0 || minute > 59 {
			return 0, false
		}
		return hour*60 + minute, true
	}
	start, okStart := parse(values[0])
	end, okEnd := parse(values[1])
	if !okStart || !okEnd {
		return 0, 0, false
	}
	return start, end, true
}

func fmtMinuteOfDay(total int) string {
	return fmt.Sprintf("%02d:%02d", total/60, total%60)
}

func main() {
	_ = os.MkdirAll("../logs", 0755)
	_ = os.MkdirAll("logs", 0755)

	zapCfg := zap.NewProductionConfig()
	zapCfg.Level = zap.NewAtomicLevelAt(zap.InfoLevel)
	zapCfg.OutputPaths = []string{"stdout", "../logs/betteragent_core.log"}

	logger, err := zapCfg.Build()
	if err != nil {
		logger, _ = zap.NewProduction()
	}
	defer logger.Sync()

	logger.Info("Starting BetterAgent Core (Go)...")

	cfg := config.LoadConfig()

	if cfg.NatsUser == "" || cfg.NatsPassword == "" {
		logger.Fatal("NATS_USER / NATS_PASSWORD are not set. Refusing to start with an unauthenticated message bus (see .env.example).")
	}
	if cfg.WebGatewayToken == "" {
		logger.Fatal("WEBGATEWAY_TOKEN is not set. Refusing to start an unauthenticated WebGateway WebSocket endpoint (see .env.example).")
	}

	// Initialize NATS Bus
	natsBus, err := bus.NewNatsBus(cfg.NatsURL, cfg.NatsUser, cfg.NatsPassword, logger)
	if err != nil {
		logger.Fatal("Failed to connect to NATS", zap.Error(err))
	}
	defer natsBus.Close()

	// Initialize Emotional & Personality System
	emoState := emotion.NewEmotionalState()
	personality := emotion.DefaultPersonality()
	circadian := emotion.NewCircadianRhythmEvaluator()

	// Initialize CentralStateMachine
	csm := engine.NewCentralStateMachine(logger)

	// Initialize UrgeEngine (cognitive impulse to speak proactively -- see
	// core/internal/engine/urge_engine.go and docs/ARCHITECTURE.md)
	urgeYAML := cfg.YAML.CoreEngine.Urge
	proactiveYAML := cfg.YAML.Integration.ToTheStars.Proactive
	quietStart, quietEnd, quietOK := parseQuietHours(proactiveYAML.QuietHours)
	urgeEngine := engine.NewUrgeEngine(engine.UrgeParams{
		AlphaBoredom:         urgeYAML.AlphaBoredom,
		BetaGameEvent:        urgeYAML.BetaGameEvent,
		GammaUnreadPressure:  urgeYAML.GammaUnreadPressure,
		BaseThreshold:        urgeYAML.BaseThreshold,
		ArousalSensitivity:   urgeYAML.ArousalSensitivity,
		EnergyPenalty:        urgeYAML.EnergyPenalty,
		MinThreshold:         urgeYAML.MinThreshold,
		MaxThreshold:         urgeYAML.MaxThreshold,
		UrgeCap:              urgeYAML.UrgeCap,
		CooldownDuration:     time.Duration(urgeYAML.CooldownSeconds) * time.Second,
		DeadZoneDuration:     time.Duration(urgeYAML.DeadZoneSeconds) * time.Second,
		GameEventDecay:       time.Duration(urgeYAML.GameEventDecaySeconds) * time.Second,
		UnreadPressureWindow: time.Duration(urgeYAML.UnreadPressureWindowSeconds) * time.Second,
		PrimaryChatID:        urgeYAML.PrimaryChatID,
		TargetSessionMaxAge:  time.Duration(urgeYAML.TargetSessionMaxAgeSeconds) * time.Second,
		// 用户在设置页「生活数据 → 主动提及策略」里的选择（config.yaml 同一段）。
		QuietHoursEnabled:   quietOK,
		QuietStartMinute:    quietStart,
		QuietEndMinute:      quietEnd,
		MaxProactivePerHour: proactiveYAML.MaxPerHour,
		MaxProactivePerDay:  proactiveYAML.MaxPerDay,
	}, logger)
	if quietOK {
		logger.Info("UrgeEngine quiet hours configured",
			zap.String("start", fmtMinuteOfDay(quietStart)),
			zap.String("end", fmtMinuteOfDay(quietEnd)),
			zap.Int("max_per_hour", proactiveYAML.MaxPerHour),
			zap.Int("max_per_day", proactiveYAML.MaxPerDay),
		)
	}

	// Autonomous game play toggle (see /game_start //game_stop handling in
	// gotd/adapter.go and webgateway/nats_bridge.go, and POST /api/game-turn
	// in webgateway/game_turn_handler.go). Default OFF -- nothing fires
	// until a human explicitly activates it.
	autonomousPlayState := engine.NewAutonomousPlayState()

	// Focus mode / pomodoro timer owner (engine/focus_manager.go). The
	// cognitive engine sends deterministic start/pause/resume/end commands
	// over NATS; this manager owns the countdown and broadcasts snapshots.
	// While a session is active it also mutes all proactive turns.
	focusManager := engine.NewFocusManager(logger)
	focusManager.StartHeartbeat(20 * time.Second)

	// Initialize ClockEngine (30s interval tick)
	clockEngine := engine.NewClockEngine(30*time.Second, natsBus, csm, emoState, personality, circadian, urgeEngine, autonomousPlayState, logger)
	clockEngine.SetFocusManager(focusManager)

	gameEventWeights := webgateway.GameEventWeights{
		DefaultWeight: cfg.YAML.GameEvents.DefaultWeight,
		Games:         cfg.YAML.GameEvents.Games,
	}

	// Initialize WebGateway WebSocket Server (Port 8080) + dedicated
	// loopback-only game-event listener (see game_event_bind_addr in config.yaml)
	webServer := webgateway.NewServer(":8080", cfg.WebGatewayToken, cfg.WebGatewayAllowedOrigins, natsBus, csm, emoState, personality, circadian, urgeEngine, autonomousPlayState, cfg.GameEventToken, cfg.LifeEventToken, cfg.YAML.CoreEngine.GameEventBindAddr, gameEventWeights, logger)
	if err := webServer.Start(); err != nil {
		logger.Error("Failed to start WebGateway server", zap.Error(err))
	}
	webServer.SetFocusManager(focusManager)
	defer func() {
		stopCtx, stopCancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer stopCancel()
		_ = webServer.Stop(stopCtx)
	}()

	// Initialize GotdAdapter
	adapter, err := gotd.NewGotdAdapter(cfg, natsBus, csm, emoState, personality, circadian, urgeEngine, autonomousPlayState, logger)
	if err != nil {
		logger.Fatal("Failed to create GotdAdapter", zap.Error(err))
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Start ClockEngine
	clockEngine.Start(ctx)

	// Initialize & Start EmotionDeltaHandler for NATS agent.emotion.delta updates
	emotionDeltaHandler := engine.NewEmotionDeltaHandler(natsBus, clockEngine.GetEmotionStore(), logger)
	if err := emotionDeltaHandler.Start(); err != nil {
		logger.Error("Failed to start EmotionDeltaHandler", zap.Error(err))
	}
	webServer.SetEmotionStore(clockEngine.GetEmotionStore())

	// Handle graceful shutdown signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		sig := <-sigChan
		logger.Info("Shutdown signal received", zap.String("signal", sig.String()))
		cancel()
	}()

	logger.Info("BetterAgent Core components initialized successfully. Ready for NATS & Telegram IO.")

	// Start GotdAdapter loop (blocks until context canceled)
	if err := adapter.Start(ctx); err != nil {
		logger.Info("GotdAdapter execution ended", zap.Error(err))
	}
}
