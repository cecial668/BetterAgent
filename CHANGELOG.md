# Changelog (变更日志)

All notable changes to the `BetterAgent` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) & [Conventional Commits](https://www.conventionalcommits.org/).

---

## [Unreleased]

### Added
- **前端「角色卡」界面接入芙宁娜（并修复"看不见当前角色卡"）**：
  - **「Better Agent 角色卡」页（settings/airi-card，localStorage `airi-cards`）**：首次启动自动写入一张内置「芙宁娜」卡（名称/描述/性格/场景/问候语/标签 + gpt_sovits `furina` 音色），只种一次——手动删除后不再自动重建；点卡片上的「激活」即可切到它。
  - 角色人设设置页现在会先拉取 `GET /api/admin/personas`，把编辑目标自动对齐到系统激活人设（`config.yaml persona.active`，当前是芙宁娜），并在页头新增**角色卡选择器**（★ 标记当前激活），可以在芙宁娜 / 空白卡之间查看与切换；此前页面固定停在 `blank`，是"看不见芙宁娜角色卡"的根因。
  - `settings/characters` 卡片网格同样内置一张芙宁娜卡（`builtin-furina`），首次打开自动写入本地；用户手动删除后不再自动重建。

### Changed
- **去猫娘化（默认白板状态）**：情绪面板标题不再写死「Camelia 情绪指标」——改为读取当前角色名（如「芙宁娜 情绪指标」），空白人设时显示中性的「情绪指标」；面板与人设页的猫头图标换成中性图标。删除示例人设 `catgirl.yaml`（Camelia）与 `patra.yaml`，保留 `blank.yaml`（白板）与 `furina.yaml`；后台"禁止删除 catgirl"的死规则一并移除；文档/测试夹具中的过时示例同步更新。
- **移除喂食功能**：删除「拖拽金枪鱼喂食」动作组件及其在桌面/移动工具栏的入口，并移除 Go WebGateway 里 `[喂食金枪鱼]` / `/feed` 的特殊加成逻辑（不再有饱和度为猫娘服务的隐藏入口）。情绪状态里的饱腹度数值本身保留。

### Fixed
- **番茄钟记录写不进向着星（HTTP 404）**：`TothestarsClient.create_focus_session` 请求路径漏了 `/api` 前缀（向着星所有路由统一挂 `/api`），导致确认提交后写入 404、她只能说"没记上"。已改为 `POST /api/focus/sessions` 并加回归测试。
- **权限开了日记摘要也看不到昨天的日记**：日记工具只有"今天"一个入口（`/api/states/today`）。现在 `tothestars_get_journal_summary` 支持 `date` 参数（问昨天/某天时传 YYYY-MM-DD），历史日期走 `/api/agent/snapshot?date=`（同一套字段）；没有日记会如实说那天没写。
- **权限矩阵缺少「专注/番茄钟」类目**：新增 `focus` 权限档（默认"可读写可主动"），门控 `focus_propose_session` 工具与专注记录写入；设置 → 生活数据 的矩阵与后台校验、config.yaml/.example 同步补齐。
- **角色卡页白屏（`Provider metadata for gpt_sovits not found`）**：内置芙宁娜卡曾把后端语音 provider 名（`gpt_sovits`）写进卡片 —— 前端 provider 注册表不认识它，激活/打开卡片弹窗时 watcher 抛错打崩整页。修复：①内置卡不再覆盖 speech provider（留空继承全局，语音本来就由 BetterAgent 后端桥接管）；②airi-card store 在注册激活 watcher **之前**自愈已写入的坏卡，并清掉已持久化到语音 store 的非法 provider（坏值一次性清除，不再复发）；③卡片创建弹窗两处 provider 元数据查找改为非抛出型（`findProviderMetadata`），即使卡片里残留未知 provider 也不再白屏。新增回归测试防止内置卡再次写死后端 provider。

### Added
- **向着星离线写入容错（两种写入通道，设置 → 生活数据 可切换）**：
  - **本地直连（默认）**：BetterAgent 进程内直接复用向着星自己的 `Database` + Service/Repo 读写其 SQLite —— 业务规则、校验与审计（`agent_audit`，actor=companion）和网页端逐字一致，向着星没启动也能写。设置页可填「向着星项目路径」，已替本机预填 `E:\ToTheStars\...\ToTheStarsWeb\ToTheStarsWeb`（数据库 = `<根目录>/data/growth_system.db`）。
  - **远程连接**：仍走 HTTP；写失败（连不上/5xx，4xx 不重试）先暂存到 `data/tothestars_outbox.json`，认知服务每 10 秒扫描、按 15s→30s→60s→120s→300s 退避补交（每次重试都静默，不让芙宁娜播报）；补交成功/放弃发 `agent.notice` → 舞台右下角轻提示 toast。她对用户的说辞也从"没记上"改成"先替你记下了，恢复后自动补上"。

- **一次生成多条写入提议（确认框排队逐条确认）**：同一轮里可以提交多条提议 —— 例如同时排「健身」「英语角」两条日程，芙宁娜会在同一轮里多次调用提议工具，系统为每条生成独立确认框，不再互相覆盖。前端改为队列：当前弹窗顶部显示「还有 N 条待确认」，点完确认/取消后自动轮到下一条（结果提示缩短到 1.4 秒），每条仍可查看详情/手动改字段。语义规则：前端按钮按提议 id 精确结算，只动那一条；语音/打字「好/取消」有歧义时只作用于最早一条；超时（10 分钟）或答非所问按条作废；同 chat 最多保留 5 条待确认（防刷屏）。日程提议工具描述已提醒模型"多条要多次调用，不要合并、不要只排一条"。

- **专注模式（番茄钟 × 向着星联动）**：对芙宁娜说「我想安静干活，大概一个小时吧」即可触发。她先语音确认并弹出「开始专注（番茄钟）」确认框（时长可调，预设 15/25/30/45/60/90 分钟，也可手填 5~240）；点确认后舞台上方出现大字倒计时挂件（渐变光圈 + 进度条 + 百分比 + 暂停/继续/结束）。规则：
  - **计时真源在 Go**（`engine.FocusManager`）：刷新页面、切标签页、短暂关闭都不丢；页面加载用 `user.focus_status` 拉回剩余时间，周期心跳广播校正。支持暂停/继续/放弃；自然结束进入 `completed` 并广播。
  - **专注期间请勿打扰**：所有主动开口（Urge 冲动、日程提醒、游戏事件、上线问候、生活桥）在 `PublishProactiveTurn` 统一静音；用户主动搭话照常回应，但认知引擎会注入「专注模式」约束——无关话题表现出被打扰的反感/抗拒/责备，不主动开新话题。
  - **自然结束**：挂件弹出「专注总结」表单（分类 + 完成了什么），提交后由认知引擎确定性写入向着星 `focus_sessions`（`POST /api/focus/sessions`，X-Actor: companion），芙宁娜围绕填写的内容做具体收尾鼓励并带上今日累计；写入失败会如实告知。
  - **半途结束**：挂件二次确认（"算半途而废，不会记录"），确认后只清状态、不落库，芙宁娜会表达失望与一点责备。
  - 协议：新增 NATS `agent.focus.command`（引擎→Go 指令）与 `agent.focus.state`（Go→认知/前端广播），WS 帧 `agent.focus_state`；控制动作沿用哨兵文本（`【专注】{v:1,...}`）走普通 `user.text`，与确认框决策同一条管线。文档见 `docs/ARCHITECTURE.md` §2.1/§4.1。

- **打开前端页面时主动打招呼（可在 设置 → 打招呼 开关）**：每次打开/刷新舞台页面，她都会主动说一句问候——随机从寒暄、今天的安排、有趣的小事、最近在忙什么、顺着上次话题、关心对方在做什么等角度里挑一个，并会提到"你多久没来"（由前端记录的两次打开间隔换算）。内容由模型现场生成，不是固定模板。
  - 链路：前端页面加载后（WS 连上时）发送一次 `user.greeting`（可带 `away_seconds`）→ Go `handleUserGreeting` 三重守卫（正在说话/思考时不打扰、10 秒冷却吸收多标签页与 F5 连击、只认 IDLE/SLEEPING/MOODY_REST）→ `PublishProactiveTurn` 复用既有主动轮管线（无新 NATS 主题、不动状态机）→ TTS 音频只发给发起招呼的页面（`MarkActive`）。
  - 前端：`betteragent-ws.ts` 新增 `onOpen` / `sendGreeting`；新增 `stores/modules/greeting.ts`（开关 + 离开时长记录，浏览器本地）与设置页 `Greeting.vue`（页面加载只在页面级触发一次，从设置页返回舞台、WS 重连都不重复）。首次访问无离开时长时按普通寒暄处理。

- **MMD 动作组（情绪/情景触发随机演绎 + 待机随机小动作）**：把原来的"一种情绪绑一个动作"升级为**动作组**——每组可放多个可互相替换的 VMD，触发时随机播放一个（多个候选时避免与上次重复）。设置 → 人物模型 → animation：
  - 9 种情绪各有一个动作组，另加「通用备选组」（某情绪组为空时回退），全部为空则只做表情不动身体。
  - 新增「待机随机动作」：开关 + 最短/最长间隔（默认 6~15 秒随机，始终可调）+ 待机动作组；空闲时随机播放，播完自动回待机。
  - 新增「说话时持续动作」（情绪分区内，默认开启）：说话期间从当前情绪的动作组里**一个接一个随机播**（动作之间停 0.4~1.2 秒），台词多长就演多长；关闭则只在情绪触发时播一个动作。与待机随机动作互相独立——一个管说话演绎，一个管空闲小动作。
  - 旧版"每情绪单动作"配置会自动迁移进对应动作组，不丢配置；导入动作后可直接在组里「+ 添加动作 / × 移除」。
  - 实现：`stores/mmd.ts` 新增动作组、待机随机与说话持续动作配置；`utils/motion-group.ts` 提供可单测的随机挑选与间隔计算（过滤未导入动作）；`MMD.vue` 分别实现两条独立调度（说话链入 `speaking` prop 由 `Stage.vue` 的 `nowSpeaking` 驱动；空闲链由倒计时驱动，说话时暂停、说完续跑）；新增 `motion-group-editor.vue` 动作组编辑器与 8 项单测。

### Fixed
- **待机随机动作"聊几句就不动了、回到僵硬立正"**：① 原实现每次说完话都把随机倒计时**从头重排**，聊天越频繁越不触发；现改为说话只暂停倒计时、说完继续（`pauseIdleMotion`/`resumeIdleMotion` 保留剩余时间）；② 下一次触发原来从"动作开始"起算，动作占用的时长会叠加成额外空档；现从"上一个动作播完"起算（`nextIdleDelayMs` = 动作时长 + 随机停顿）；③ 默认间隔 20~60 秒收紧为 6~15 秒。基础站姿仍由「待机动作」决定，设置页提示文案已注明僵硬度多半来自静态待机循环。

### Changed
- **芙宁娜角色卡说话方式调整（config/persona/furina.yaml）**：① 简短优先——默认 1～2 句、最多 3 句，只有对方明确要求展开才允许到 5 句，杜绝"问一句答三行"；② 自称统一为「我」，禁止「本神」等旧称呼；③ 过去只作为性格底色，不在无关话题里主动搬出"歌剧/审判/五百年/水神/枫丹/预言"，相关时也像普通人讲旧工作一样一句带过；④ 现代日常口语为主，戏剧化措辞降为调剂（dramatic_flair 0.95→0.45），睡迷糊台词与联网提示文案同步去掉旧称呼与旧事。

### Added
- **向着星写入「确认框」（取代纯文本确认，修复"反复说好不生效"）**：数字人生成提议后不再要求用户打字回复，而是在舞台弹出全局确认框、在向着星对话气泡内弹出确认卡片；可「查看详情」并手动修改白名单字段（标题/难度/日期/必要委托……），点「确认/取消」后由引擎确定性执行，并把结果作为系统事件交回模型产生语言反馈；取消/超时/答非所问会关闭确认框且零写入。
  - 链路：`cognitive_engine` 提议时生成唯一 id 并产出 `LifeProposalPayload`（pending→executing→executed/failed/cancelled/expired）→ NATS `agent.life.proposal` → Go 转发 WS 帧 `agent.life_proposal` → 前端确认框；用户决定以哨兵文本走普通 `user.text` 回传（不新增通道、聊天记录不出现机器消息）。
  - 舞台：新增 `LifeProposalDialog.vue`（全局弹窗，可编辑）；向着星：`agent-chat.js` 新增确认卡片并支持编辑。
  - 编辑服务端二次校验：`apply_life_proposal_edits` 白名单 + 归一化，执行仍走 `execute_proposal` 完整校验。
- **向着星（ToTheStars）生活系统联动（P0→P2 全量落地；设计文档 [`docs/TOTHESTARS-INTEGRATION-PLAN.md`](docs/TOTHESTARS-INTEGRATION-PLAN.md)）**：
  - **向着星侧**：新增 `agent_audit` 表与审计仓储/撤销分发；`GET /api/agent/snapshot`（今日快照）、`GET /api/agent/audit`、`POST /api/agent/audit/{id}/undo`、`GET /api/agent/chat-config`；全部写路由按 `X-Actor` 记录来源（委托与日程可撤销、传说指标可撤销、批量与日记仅记录、日记只记元数据不存正文）。前端新增「AI 活动」页（来源标记 / 筛选 / 一键撤销 / 撤销留痕）与右下角对话气泡（直连 WebGateway，未配置 `AGENT_WS_TOKEN` 时零渲染）。
  - **认知侧（权限与工具）**：新增 `shared/life_data_permissions.py` 作为四档权限（可读写可主动 / 只读可主动 / 问起才读 / 完全不可见）的唯一真源，工具可见性与提示词注入共用同一判断；`services/cognitive/tools/tothestars_tool.py` 提供只读工具族 + **提议工具族**；`cognitive_engine` 每轮按权限门控 tools_schema，并实现**写入确认协议**（模型看不到任何写执行工具，用户确认/取消后由引擎确定性执行，10 分钟 TTL、超时/答非所问安全作废、执行前后二次校验权限）；`prompt_builder` 注入生活快照与克制规则（数据当数据、没有的不编造、日记不主动提、确认前不许说已完成）。
  - **配置与界面**：`config/config.yaml` 新增 `integration.tothestars`（权限矩阵 + 主动策略）；Admin `/api/admin/config` 读写与白名单校验；设置页新增「生活数据（向着星）」（可见范围即时预览、6 类数据 × 4 档矩阵、静默时段/频率上限）；舞台新增 `LifeHUDWidget`（今日委托完成度 / 下一项日程 / 传说进度 / 「让她讲讲今天」），经新增的 `/api/admin/tothestars/*` 反向代理读取以避免跨域。
  - **主动层**：Go 新增 `POST /api/life-event`（独立 `LIFE_EVENT_TOKEN`、权重表 `game_events.games.life`，与游戏事件共用 `:8090` 回环监听）；`UrgeEngine` 新增静默时段（支持跨零点）与每小时/每天主动上限（按实际开口计，对所有主动消息生效）；新增 `services/life_bridge/life_poller.py`（晨间简报 / 晚间复盘 / 传说临期 / 必要未完成 / 连续完成里程碑，按天去重、尊重开关、配置按 mtime 热更新）并由 `runner.py` 守护。
  - **验证**：Go `go test ./...` 全绿（新增生命周期事件 9 测 + 静默/频率 4 测）；桥与权限/工具/协议 Python 测试全绿；前端 store vitest 与 lint 通过；合并验收脚本 22 项（权限门控、快照一致性、确认协议、审计撤销、日记边界、静默/频率、离线降级、HUD 代理）全部通过。
- **联网搜索 Layer 1：`web_search` 工具本体（Tavily 后端）**：
  - 新增 `services/cognitive/tools/web_search_tool.py`：请求超时、结果条数钳制（1~10）、URL 清洗、以及 `<untrusted_content>` 提示词注入防护信封（标题/日期与正文一起进信封，信封外只留 sanitize 过的 URL）；缺少 Key / 超时 / 非 2xx / 非 JSON / 网络异常一律优雅降级为 `status=failed`，不炸整轮对话。
  - `ToolRegistry` 注册 `web_search`；`cognitive_engine` 每一轮按 `tools.web_search.enabled` + API Key 门控（关闭时模型**根本看不到**该工具，而不是"看得到但被劝阻"），并遵守 `max_calls_per_turn` 单轮次数上限；`prompt_builder` 仅在可用时注入「联网搜索能力 + 网页内容安全规则」，与信封成对出现、缺一不可。
  - `web_search` 结果并入既有 citations 通道（前端「参考资料」面板），面板展示前自动剥掉信封标签。
- **联网搜索 Layer 2：角色卡联网字段 + 角色卡字段说明面板**：
  - 角色卡新增 `web_search` 段：`enabled`（角色级开关）/ `style`（7 种说法预设：neutral・phone・divination・library・informant・oracle・custom）/ `alias`（这个能力在角色语境里叫什么）/ `missed`（查不到时怎么说）/ `framing`（整段自定义说法）。渲染逻辑集中在 `shared/web_search_persona.py`，它是提示词侧与工具门控侧的唯一真源。
  - **三层门控**：全局开关（`tools.web_search.enabled`）× 角色卡开关（`web_search.enabled`，缺省跟随全局）× 单轮次数上限，共同决定模型这一轮"看不看得见"联网工具；提示词里那段能力说明与「分寸」也随之同步注入/撤下，不会出现"关掉了但模型还想着查"。
  - **人设不割裂的关键约定**：语气化内容（alias / framing / missed）可由角色卡自由覆盖，但「该查 / 不该查 / 角色自己的世界一律不查」是硬规则，写在 `shared/web_search_persona.py`，角色卡覆盖不了。
  - 设置页人设编辑器新增「联网能力」tab，以及右上角 **ⓘ 角色卡字段说明** 面板：逐字段列出含义、示例文本与填写注意事项（含"改完是否需要重启"标记）。
  - 芙宁娜角色卡按此新增字段（`style: phone` + 芙宁娜口吻的 `missed`/`framing`）；`config/persona/blank.yaml` 补上带注释的字段模板。
- **联网搜索 Layer 4：搜索进行中的角色化提示（呼吸光）**：
  - 新增 NATS 主题 `agent.tool.activity` 与 `ToolActivityPayload`（Python / Go 两侧字段一一镜像），Go WebGateway 转发为 WS 帧 `agent.tool_activity`。**故意不动 CSM 状态机** —— "正在查资料"是工具级的瞬时事件，不是对话状态，塞进状态机会和状态机打架。
  - `cognitive_engine` 在 `web_search` 执行前后各发一条 `phase=start|done`（失败也发，否则提示会一直转）；`label` 由角色卡渲染，前端只负责原文显示，不自己拼"正在搜索互联网…"。
  - 字幕浮层新增一行带**呼吸光**的提示（`@keyframes tool-activity-breathe`，并尊重 `prefers-reduced-motion`）。
  - 新增角色卡字段 `web_search.searching`（7 个预设各带默认文案，如 `phone` → 「正在翻手机查资料…」）。它是整张角色卡里**唯一会直接露给用户看的联网文案**（不走提示词，是纯界面文字）。设置页「联网能力」tab 与 ⓘ 字段说明面板同步补齐，芙宁娜角色卡写入她的口吻（「本神正在翻手机查资料…」）。
- **联网搜索 Layer 3：来源面板链接化与措辞角色化**：
  - 字幕浮层来源面板的 `source` 从纯文本改为**可点击链接**（显示域名、`title` 给完整 URL、`target="_blank"` + `rel="noopener noreferrer"`；`@click.stop` 避免点击被浮层的拖拽处理吞掉）。
  - 面板标题由「参考资料 (N)」改为角色化措辞「她的消息来源 (N)」。
- **联网搜索测试覆盖补齐**：`tests/test_web_search_tool.py` 的引用收集断言改为按"有没有 `citations`"筛选（新增的进度事件不带 `citations`），并补上 `start` → `done` 顺序断言；`tests/test_persona_web_search.py` 补 `render_web_search_activity_label` 的覆盖（预设默认 / 单字段覆盖 / 人设关网时为空）。
- **iFLYTEK 科大讯飞 STT Provider (`services/stt/`)**：
  - 新增 iFLYTEK WebSocket 流式 STT Provider，支持从浏览器 ScriptProcessorNode 采集 PCM 并通过 WebSocket 推送至后端实时转写。
  - 缺少 iFLYTEK 凭据时自动回退至 FunASR 离线 Provider。
- **MCP Presenter 会话复活 (`services/mcp_ppt/`)**：
  - 优化 presenter_manager 会话重激活逻辑与 Win32 窗口 Docking 机制。

### Fixed
- **MMD 对话动作把角色带偏（播放时跑到侧边、转身侧对镜头 + 转场绕圈滑行）**：多套配布的"背景角色用对谈动作"把站位与朝向焊死在首帧上（实测 `センター` x=±8、偏航 ±91°）。最终实现 **根骨骼首帧归一化**（`loadMMDAnimationClip` 默认开启）：计算首帧整套骨架的"放置变换"，把它的逆**逐顶层分支烘焙**进动作数据——身体分支（`センター`）与独立顶层分支（左右 `足ＩＫ`）应用同一个刚体反向旋转/平移，上身与腿始终一致（曾经的"只转正センター"实现会让上身朝前、双腿劈叉；"只修 `全ての親`"实现会在动作交叉淡化时因根旋转与零位混合而绕原点滑行半圈，两版均已废弃）；修正后每个动作的根骨骼都是中性的，跨动作混合不再转圈。姿势内部骨头一根不改，点头/晃动/前倾全部保留。朝向基准优先用根骨骼；个别文件把朝向"拆开写"（如 `xs-talk4-east`：根骨骼 -91°、身体又反向拧回 +115°，身体实际朝向 +24°），此时以身体链（上半身）的实际朝向为基准，避免修正后反而侧脸；两者相差小于 45° 的文件维持根骨骼基准、行为不变。MMD 设置页提供「对话动作锁定站位与朝向」开关（默认开，舞蹈类动作可关；切换即重新加载动作）。4 个单元测试覆盖身体+腿部一致转正、拆分朝向按身体基准、内部骨骼不受影响、无顶层分支时安全跳过。
- **同一句语音被播两遍（"二重奏/齐读"）**：服务端日志确认每条语音只合成一次，问题是客户端有两条播放链路在放同一份音频。两层修复：① 同一页面只允许一个 BetterAgent 音频订阅者（把清理函数挂 window，新的挂载/HMR 先移除旧订阅，杜绝热更新或重复挂载导致的叠播）；② 同一 chat 多页面连接时，音频只发给"最后发言"的那个页面（Go `SessionManager` 新增 `MarkActive`，`SendBinaryToChat` 单播+回退广播），不再两个标签页各播一遍。另：确认框点「确认/取消」现在会立即打断正在播报的提议语音，避免和确认后的回复叠在一起。
- **写入确认在真实对话里永远不生效（"反复说好也没用"）**：舞台聊天会给每条消息加上 `[YYYY-MM-DD HH:MM] ` 时间戳前缀再发给后端，而确认词判定与哨兵解析按原文匹配，于是"好"永远匹配不上 —— 提议被静默作废，模型只能一遍遍重新提议，用户看到的就是"一直让我再确认"。现统一在判定前剥掉前导 `[...]` 前缀，并补了带前缀的回归测试与 E2E 用例。
- **字幕浮层的「搜索中」提示从来没显示过 —— 前端把带 `chat_id` 的 WS 帧整类丢了**：`betteragent-gateway.ts` 的 `isChatMatch()` 拿本地解析出的**子 id**（URL / `localStorage`，例如 `6174113`）去比 Go 回传的**折叠后 id**（子 id + `WebNamespaceOffset`，例如 `9000000006174113`），两者永不相等，于是 `agent.tool_activity`（联网搜索的呼吸光提示）与 `agent.state_change` 这些带头 `chat_id` 的帧被静默丢弃 —— 用户看到的就是"问完一直卡着、没有任何搜索过程"。现把两侧统一折回子 id 再比较（新增 `toSubChatId()`）。顺带把 `WEB_NAMESPACE_OFFSET` 从 `services/schedule-api.ts` 搬到 `services/betteragent-ws.ts`（chat_id 语义归属于 WS 协议层），`schedule-api.ts` 改为 re-export，`ScheduleHUDWidget.vue` 无需改动。
- **联网搜索的「参考资料」面板时有时无 —— 无文字的收尾决策被 Go 整个丢弃**：一轮流式输出结束时，若尾部 flush 已经没有句子可播，`cognitive_engine` 会单独发一条 `text_content=""` + `is_final=true` 的 `ActionDecision`，并把本轮的 citations 挂在它身上；而 `nats_bridge.go` 的 `handleActionDecisionMsg` 主分支要求 text 非空，这条决策被静默跳过，浏览器永远收不到 citations（只有尾部恰好还剩一句可播时才会亮，所以表现为"时有时无"）。现补一个 `else if len(decision.Citations) > 0` 分支把空文字 + citations 转发出去；前端 `agent.text_delta` 的判空条件把 citations 也算上，且这类帧**只用来补 citations、不参与流生命周期**（它比最后几句的 TTS 回灌还早到，若参与开流/收尾会把尾句甩到流外）。新增 Go 回归测试 `TestHandleActionDecisionMsg_CitationsOnlyFinalDecision_ForwardedToBrowser` 与 `TestHandleActionDecisionMsg_NoTextNoCitations_NoTextDeltaForwarded`。
：该页读写的是 AIRI 上游那套只存 `localStorage` 的 module store，Key 只活在浏览器里，Python 认知服务永远读不到 —— 这正是"开关打开了也没反应"的根因。现改为直连 admin 配置接口（`GET/PATCH /api/admin/config`）：开关与数值落 `config/config.yaml` 的 `tools.web_search`，Key 落根目录 `.env` 的 `TAVILY_API_KEY`，保存即发 `agent.config.reloaded` 热刷新（**无需重启 `runner.py`**）。后台不可达时页面转为只读并给出直接改文件的确切位置，而不是"看起来能用但没反应"；开关打开但未填 Key 时也会明确警告"模型仍然看不到该工具"。
- **Admin 配置写入会把 `config/config.yaml` / `.env` 的换行符改成 CRLF**：`_atomic_write_text` 与 `_write_config_rt` 走的是 Windows 默认的换行翻译，于是从设置页保存一次就会把整份 LF 文件重写成 CRLF —— 与仓库 `.gitattributes` 的 `eol=lf` 冲突，还产生"整份文件都动了"的假 diff。现显式 `newline="\n"`，保存后文件字节不变（`.env` 仅在原文件缺结尾换行时补一个，属正常化）。
- **OpenAI 兼容 Provider 的工具往返被静默丢弃**：`CognitiveEngine._append_tool_round_trip` 写入的 `role="model"`/`function_call` 与 `role="user"`/`function_response` 在 `OpenAIProvider._build_messages` 里没有对应分支，于是 DeepSeek/Qwen 等 OpenAI 兼容端点上看不到任何非即发工具（`search_campus_kb`、presenter 的 `ppt_*`/`vscode_*`、以及新增的 `web_search`）的真实返回值，只能靠猜。现翻译为标准的 `assistant.tool_calls` + `role:"tool"` 配对消息（Gemini/Claude 侧原本就正确）。
- **Admin 用户/会话列表过滤**：过滤遗留 mock 测试用 `chat_id` 与用户画像，避免测试数据污染 B 端控制台。
- **STT AudioWorklet**：改用 ScriptProcessorNode 规避 iFLYTEK 下 AudioWorklet 采集无声问题；添加 AudioContext 恢复状态日志。
- **Go Core WebGateway**：PCM 边缘平滑处理 + 真正 GPT-SoVITS 分块流式推送 + generation_id 同步修复。

---

## [v1.9.0] - 2026-08-24

针对 `docs/ARCHITECTURE.md` 的一轮完整代码审查发现的严重缺陷、并发缺陷与死代码，分四轮修复：核心链路 Bug 修复、剩余缺陷与死代码清理、STT 中间转写全链路打通、文档同步。

### Added
- **BYOK Provider 配置热更新消费端 (`services/cognitive/`)**：订阅 Admin 后端发布的 `agent.config.reloaded`，调用 `ProviderFactory.invalidate_cache()` + `CognitiveEngine.refresh_default_provider()`，切换 LLM Provider/API Key 无需重启服务。
- **STT 中间转写结果（partial transcript）全链路打通**：Go `nats_bridge.go` 新增订阅 `agent.stt.stream_partial` 并转发为 WS `agent.stt_transcript`（`is_final:false`）；前端 `betteragent-gateway.ts` store 新增 `partialTranscript` 响应式状态（UI 展示留待后续实现）。

### Fixed
- **人设热更新链路打通**：修复 `admin/backend/main.py` 的 `.env` 加载顺序崩溃；`patch_persona` 补上写盘成功后向 NATS 发布 `agent.persona.update`（响应体新增 `hot_reload` 字段）；修复 `services/cognitive/main.py` 缺失的 `PersonaLoader` 导入（此前每次热更新消息都会静默抛 `NameError`）。
- **Barge-in 打断正确性**：去掉 `generation_id == 0` 时跳过过期校验的漏洞；修复 `memory_hub.py` 未转发 `generation_id` 导致被 pydantic 默认值重置的问题；前端追踪逐 chat 的 `generation_id` 并丢弃过期二进制音频帧；`agent.state_change` 的 idle 事件新增 `reason` 字段以区分"正常说完"与"被打断"，避免误伤正常收尾的音频；二进制音频帧改为携带该帧自身的 generation（而非当前 generation）。
- **Companion 推荐接口时区 Bug**：修复 `recommendation.py` 时区朴素时间戳与带时区时间戳相减抛未捕获 `TypeError`（导致 `/api/companion/recommendations` 500）的问题，统一按 `Asia/Shanghai` 解释朴素时间戳。
- **Go 情绪状态数据竞争与跨会话状态错用**：新增 `EmotionalState.GetMoodTag()`/`GetAffectionLevel()` 加锁 getter 替换多处锁外裸读；修复 `game_event_handler.go` 与 `game_turn_handler.go` 两处濒死/胜负事件误用全局兜底情绪状态而非目标会话专属状态的问题。
- **campus_kb 并发 ingest 缺陷**：`KnowledgeStore.ingest()` 新增 `asyncio.Lock`，改为写入后再排除新写入 ID 删除旧内容（write-before-delete），修复并发重复入库、重新入库时短暂出现空窗口、以及批量入库中单个来源清理失败会中止整批处理的问题。
- **跨会话记忆泄漏**：`AgentSelfMemory.self_events` 由进程级扁平列表改为按 `chat_id` 分桶，避免不同会话的自我事件互相串场。
- **admin 后端 `.env` 加载崩溃**、**runner.py 误杀 Docker 托管端口进程**（端口列表移除 Docker 管理的 `10095`/已废弃的 `50000`，加入 companion 服务的 `8096`）。

### Changed
- 清理一批确认无调用点、无架构文档依据的死代码（Go：`CentralStateMachine.GetCurrentState`/`TransitionTo` 旧接口、`SessionManager.BroadcastText`、`MediaManager.CleanOldFiles`、重复的 `SubjectWebUserInterrupt`；Python：`campus_kb/retrieval.py` 的 `rrf_fusion()`、若干未使用的 import），对"没有调用点但看起来是预留接口"的代码保守保留不删。

---

## [v1.8.0] - 2026-08-22

### Added (Supervisor、Admin Panel & Companion 全面集成)
- **Supervisor & Admin Panel Integration (`runner.py`)**:
  - 集成 Admin Backend REST Service (`:8094`) 与 Admin Frontend Vue Service (`:8095`) 到 `runner.py` 进程守护，支持跨平台 CLI 路径探测（`find_cli_cmd` / `shutil.which`）。
  - 新增 `:8094`、`:8095`、`:5173` 端口占用的启动前清理逻辑。
- **Companion Schedule & Memory Integration (`services/companion/`)**:
  - 集成 `ScheduleHUDWidget.vue` 浮动日程小组件与 `Schedule.vue` 操作按钮至 `stage-web`。
  - 新增 `companion_tool.py`，使 Cognitive LLM 可通过 HTTP 调用 `:8096` 管理用户日程。
  - 新增 `schedule-api.ts` 与 `memory-api.ts`，支持前端直接访问记忆与提醒接口。
- **Gotd MTProto 无会话文件优雅处理 (`core/internal/gotd/`)**:
  - 实现 `HasSessionFile()` 检查，`gotd.session.json` 不存在时跳过 MTProto 登录，避免首次启动 panic。
- **API Contract & Team Subservice Boundary (`docs/API-CONTRACT.md`)**:
  - 定义 Campus KB (`:8093`)、Admin Panel (`:8094`/`:8095`)、Companion (`:8096`) 的 HTTP REST 接口规范与端口隔离策略。
  - 新增自动化集成测试 (`tests/test_api_contract.py`) 作为 PR 合并门控。

### Fixed
- **Frontend Build**：升级 `stage-web` 与 Admin Frontend 的 Vite 构建依赖。
- **MobileInteractiveArea.vue / ChatArea.vue**：新增空 `providerId` 防护，避免 WebSocket 桥模式下控制台报错。
- **Admin Backend (`admin/backend/main.py`)**：Qdrant API Key 头部、WebGateway chat_id 命名空间、用户画像 key 命名空间对齐修复；补充模块级 `QDRANT_API_KEY` 变量定义。
- **Memory Service**：强制 Redis RESP2 协议兼容旧版 Windows Redis Server。

---

## [v1.7.0] - 2026-08-20

### Added (Sprint A — 前端人设控制面板 & Emotion HUD)
- **4-Tab 人设控制面板 (`/settings/persona`)**：
  - 支持在线 System Prompt 编辑、基础身份设置、tsundere/clingy 权重编译与交互边界配置。
  - 双渠道更新管道：Admin REST API (`:8094`) HTTP PATCH 持久化 YAML 磁盘 + WebSocket `admin.persona_update` 帧发送至 Go Core，触发 NATS `agent.persona.update` 广播，实现 Python `PersonaLoader` 零停机内存热重载。
  - 新增 `stripCompiledHeader` 函数，保证编译后 Prompt 头部被正确剥离，重复保存时 100% 幂等。
- **EmotionHUDWidget.vue**：
  - 浮动 HUD 组件，实时显示 3D VAD 指标（Valence/Arousal/Dominance）、Affection、Energy、Social Battery 与 Jealousy 状态，由 `AgentEmotionPayload` WebSocket 帧驱动。
- **VisionPrivacyIndicator.vue**：移动至左上角 (`left: 16px`) 解决与其他 UI 按钮重叠问题。

---

## [v1.6.0] - 2026-08-19

### Added (Sprint 7 — Prompt 优化 & Token 裁剪)
- **PersonaLoader TTL 内存缓存**：消除每次请求的 YAML 文件磁盘 I/O。
- **`PromptBuilder.build_system_prompt()` 按场景裁剪**：`game_turn` 模式下跳过非游戏记忆与 KB 章节，节省 100-500 tokens/轮。
- **`agent_self_events` 压缩**：保留最新 1-2 条详细动作，历史动作聚合为计数摘要，节省 60-80% tokens。

---

## [v1.5.0] - 2026-08-18

### Added & Fixed (Sprint 6 — MCP 子进程生命周期防挂起)
- **`presenter_sweep_loop`**：`main.py` 新增后台扫描协程，每 60s 调用 `sweep_idle()` 防止 PPT/VSCode 孤儿子进程泄漏。
- **`asyncio.wait_for` 超时守卫**：为 `McpSession.start()` 与 `McpSession.call_tool()` 添加超时门控，防止协程永久挂起。

---

## [v1.4.0] - 2026-08-18

### Added & Refactored (Sprint 5 — LLM Provider 接口标准化)
- **`BaseLLMProvider` 抽象契约**：定义 `generate_stream()` 抽象方法与 `supports_vision()` 能力 Hook。
- **`ClaudeProvider` 全异步重构**：切换至 `anthropic.AsyncAnthropic` 流式工具调用引擎，添加 API Key 安全警告与 ID 关联校验。
- **`GeminiProvider` 去阻塞化**：移除 `loop.run_in_executor` 线程池阻塞，委托给 `generate_stream()`。

---

## [v1.3.0] - 2026-08-17

### Added (Sprint 4 — 自我记忆 & 人设清理)
- **`AgentSelfMemory`**：在 `memory_hub.py` 中集成 Agent 自我行为反思追踪。
- **Persona 名称去硬编码**：将硬编码人名替换为 `get_config_val("persona.default_user_name", "主人")` 配置注入。

---

## [v1.2.0] - 2026-08-17

### Added (Sprint 3 — Campus KB 集成)
- **并发上下文增强**：在 `memory_hub.py` 中使用 `asyncio.gather` 并发执行个人 RAG、Campus KB (`:8093`) 与 UserProfile 上下文注入。
- **服务就绪探针**：在 `runner.py` 中为 `campus_kb_service` 添加启动探针与 Supervisor 管理。

---

## [v1.1.0] - 2026-08-16

### Added & Refactored (Sprint 1-2 — 记忆现代化 & Token 预算)
- **Redis 异步连接池**：将 `short_term_buffer.py` 升级至 `redis.asyncio` 连接池。
- **AsyncQdrantClient**：在 `services/memory/vector_store.py` 中实现异步向量存储，支持多 Provider 嵌入回退（OpenAI/Gemini/HashedNgram）与 Ebbinghaus 衰减评分。
- **主动记忆归档 (`consolidator.py`)**：实现 LLM 提取事实写入向量存储的主动归档流程。
- **UserProfile Redis Hash 持久化**：在 `user_profile.py` 中实现用户事实画像的 Redis Hash 持久化。
- **CJK 加权 Token 估算 (`token_budget.py`)**：防止亚洲语言文本 Token 溢出。
- **`SentenceSegmenter` JSON 边界正则修复**：收窄正则，防止包含 `{` 的有效文本被误判截断。
- **`stream_reasoning_loop` 异常处理**：强制补发 `is_final=True` 兜底 Payload，解除 Go Core CSM 看门狗因异常阻塞的情形。

---


## [v1.0.0] - 2026-08-15

### Added
- **Go Core Microservice Engine (`core/`)**:
  - `CentralStateMachine`: Per-chat concurrency isolation (`sync.RWMutex`) with 45s Deadman Switch Watchdog timer.
  - `EmotionEngine`: 3D VAD (Valence, Arousal, Dominance) affective model with physical indicators (Energy, SocialBattery, Affection).
  - `CircadianRhythm`: Biological clock decay evaluator driving night/sleep prompt switches.
  - `UrgeEngine`: Boredom and game event energy accumulator triggering proactive speech opportunities (`agent.inbound_message`).
  - `GotdAdapter`: High-concurrency Telegram MTProto client with automatic typing heartbeats and media IO.
  - `WebGateway`: Full-duplex WebSocket gateway (:8080) for web frontends (`stage-web` / Live2D / VRM).
- **Python Services Layer (`services/`)**:
  - `CognitiveService`: Multi-provider LLM engine (Gemini 2.5/3.0, Claude 3.5/3.7, OpenAI) supporting streaming function calling, TTS speech generation, and ImageGen.
  - `MemoryService`: Redis short-term conversation buffer + Qdrant vector memory store + UserProfile fact extractor + Ebbinghaus memory consolidation (`MemoryConsolidator`).
  - `TTSService` & `STTService`: Real-time cancelable streaming voice synthesis (GPT-SoVITS / Edge-TTS) with viseme lip-sync packet generation and FunASR speech-to-text.
- **Frontend Digital Human Application (`frontend/apps/stage-web`)**:
  - Vue 3 + TypeScript + UnoCSS frontend with Live2D/VRM avatar rendering, real-time audio chunk playback, emotion expression binding, and WebSocket status sync.
- **Process Supervisor (`runner.py`)**:
  - Production-grade process orchestrator with win32 Job Object cleanup, circuit breaker restart backoff, and non-blocking VT100 log formatting.
