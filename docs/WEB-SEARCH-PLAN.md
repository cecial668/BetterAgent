# BetterAgent 待实现功能与方案：联网搜索

> 文档状态：**Layer 1 ~ Layer 4 已实现并自测通过；只剩可选的抓正文 / 本地缓存向量化**  
> 更新日期：2026-09-11（第二轮）  
> 实现进度：L0 全局开关 + Layer 1 搜索工具 + Layer 2 角色卡字段/字段说明 + Layer 3 来源链接化 + Layer 4 搜索中提示与设置页打通，详见 §0.5  
> 适用仓库：`D:\college\2027qiu\数字人\BetterAgent-main\BetterAgent-main`  
> 目标读者：本项目维护者（尽量少术语，结论先行）

---

## 0. 一分钟结论

1. 联网搜索本身**容易做**，架构不用动，属于「加一个工具」级别。
2. 真正的不确定性**只有一个**：模型愿不愿意调这个工具（下称**触发率**）。
3. 因此建议先做**最小验证版 P1（约半天）**，用真实 API key 实测触发率，再决定要不要继续投入。
4. 联网能力必须加在 **Python 认知服务**侧——前端已经有一份现成实现，但对本项目**完全失效**（原因见 2.1）。
5. 开关做**两级**（全局 + 角色卡）；「怎么把搜索说出口」写进**角色卡**，并附 6 个预设风格以兼容各类人设。
6. 工作量估算：最小集 P1~P3 约 **2~3 天**；完整四层约 **4~6 天**；触发率调优需要本人参与，另加 1~3 天。

---

## 0.5 实现进度（2026-09-11 更新）

| 层 | 内容 | 状态 |
| --- | --- | --- |
| L0 | 全局开关 `tools.web_search` + `shared/web_search_config.py` + admin 接口 + 前端设置页 `/settings/web-search` | ✅ 已完成 |
| L1 | `web_search` 工具本体 + 注册 + 每轮门控 + 引用收集 + prompt 注入 | ✅ 已完成（`tests/test_web_search_tool.py`，22 项） |
| L1 附带 | **修复 OpenAI 兼容 Provider 工具往返被丢弃**（见下） | ✅ 已完成 |
| L2 | 角色卡 `web_search.*` 字段 + 7 预设 + 两处白名单 + 提示词注入 + 设置页 tab | ✅ 已完成 |
| L3 | 来源面板：`source` 渲染成可点击链接 + 标题角色化（「参考资料」→「她的消息来源」） | ✅ 已完成（第二轮） |
| L4 | 搜索进行中的角色化提示：NATS `agent.tool.activity` → WS `agent.tool_activity` → 字幕浮层上的呼吸光提示；文案来自角色卡 `web_search.searching` | ✅ 已完成（第二轮） |
| L5 | 抓正文 / 本地缓存向量化 | ⬜ 未开始（可选） |

> 编号说明：本表按**实现顺序**编号（L3 与 L4 都属于 §3 里那一层「前端展示」），§3/§4 则按**方案分层**写，
> 两者不是同一套序号，对照时以本表为准。

**第二轮（Layer 3 / Layer 4 + 设置页）落地清单**

1. **设置页真正可用**（原为"死设置"，见 §2.1）。落点：
   - `frontend/packages/stage-ui/src/components/modules/WebSearch.vue`（整页重写）：开关、
     Key（password + 掩码回显 + **留空 = 不改 Key**）、`top_k` / `timeout_seconds` / `max_calls_per_turn`。
   - `frontend/packages/stage-ui/src/services/betteragent-admin-api.ts`（新增）：`getWebSearchConfig`
     / `updateWebSearchConfig`；PATCH 只回 `{status, reloaded}`，所以写完必须再 GET 一次拿权威状态。
   - **职责切分**：这一页只管"能不能联网"；"什么时候该查 / 查到了怎么说 / 正在查的时候显示什么字"
     全归角色卡。换一个角色（古代剑客、清朝格格）不需要动这一页。
2. **搜索进行中的提示（Layer 4）**。链路是"Python 发事件、Go 转发、前端只负责显示"：
   - `shared/subjects.py` / `core/internal/bus/nats_bus.go`：新增主题 `agent.tool.activity`。
   - `shared/schema/payloads.py` / `core/internal/schema/payloads.go`：新增 `ToolActivityPayload`
     （`chat_id` / `tool` / `phase`=start|done / `label`），Python 与 Go 两侧字段一一镜像。
   - `services/cognitive/cognitive_engine.py`：`web_search` 执行**前**发 `phase=start`、执行**后**发
     `phase=done`（失败也要发，否则提示会一直转）。`label` 由 `render_web_search_activity_label()` 按角色卡渲染。
   - `core/internal/webgateway/nats_bridge.go`：订阅后转发为 WS 帧 `agent.tool_activity`（**故意不碰 CSM**
     —— "正在查资料"是工具级的瞬时事件，不是对话状态，塞进状态机会和状态机打架）。
   - 前端 `betteragent-ws.ts` → `betteragent-gateway.ts` → `live-caption-overlay.vue`，
     显示一行带呼吸光（`@keyframes tool-activity-breathe`）的提示，并尊重 `prefers-reduced-motion`。
3. **来源面板（Layer 3）**：`live-caption-overlay.vue` 里 `source` 从纯文本改成可点击链接
   （显示域名、`title` 给完整 URL、`target="_blank"` + `rel="noopener noreferrer"`；
   `@click.stop` 是必须的 —— 浮层本身有拖拽处理，不拦住的话点击会被吞掉），
   面板标题改为角色化措辞「她的消息来源 (N)」。
4. **角色卡新增 `web_search.searching`**：7 个预设各带默认文案（如 phone → 「正在翻手机查资料…」）。
   这是整张角色卡里**唯一会直接露给用户看的联网文案**（不走提示词，是纯界面文字）。
   落点：`shared/web_search_persona.py`、两处 `WEB_SEARCH_PATCHABLE_FIELDS` 白名单、
   设置页「联网能力」tab、ⓘ 字段说明面板、`config/persona/furina.yaml` 与 `blank.yaml`。
5. **顺手修掉的换行符缺陷**：admin 侧 `_atomic_write_text` / `_write_config_rt` 走的是 Windows 默认换行翻译，
   于是从设置页保存一次，就会把 `config/config.yaml`（和填 Key 时的 `.env`）从 LF 整体改写成 CRLF ——
   与本仓库 `.gitattributes` 的 `eol=lf` 冲突，还会产生"整份文件都动了"的假 diff。现显式 `newline="\n"`。

**真机验证时发现的两个缺陷（第三轮，均已修复）**

第一轮真机测试中，「搜索进行中」的提示**一次都没出现**，但后端日志显示 `web_search` 确实被调用了。
用「同一 chat 的双通道探针」（同时裸连 NATS 与 WS，逐帧打时间戳）逐段核对后，定位到两个互不相干的缺陷：

1. **前端把带 `chat_id` 的 WS 帧整类丢掉了** —— 「搜索过程」不显示的真因。
   `betteragent-gateway.ts` 的 `isChatMatch()` 拿本地解析出的**子 id**（URL / `localStorage`，
   例如 `6174113`）去比 Go 回传的**折叠后 id**（子 id + `WebNamespaceOffset`，例如
   `9000000006174113`），两者永不相等，于是 `agent.tool_activity`（呼吸光提示）与
   `agent.state_change` 这类带 `chat_id` 的帧全部被静默丢弃。这正是"问完一直卡着、
   没有任何搜索过程"的来源；`agent.state_change` 被丢掉还意味着前端 CSM 状态长期停在
   `idle`。修法：两侧统一折回子 id 再比较（新增 `toSubChatId()`），并把
   `WEB_NAMESPACE_OFFSET` 收进 `services/betteragent-ws.ts` 作为唯一真源
   （`services/schedule-api.ts` 改为 re-export）。
2. **无文字的收尾决策被 Go 整个丢弃** —— 「参考资料」时有时无的真因。
   一轮流式输出结束时，若尾部 flush 已经没有句子可播，`cognitive_engine` 会单独发一条
   `text_content=""` + `is_final=true` 且挂着本轮 citations 的 `ActionDecision`；而
   `nats_bridge.go` 的 `handleActionDecisionMsg` 主分支要求 text 非空，这条被直接跳过。
   探针实测：NATS 上出现 `final=True text='' citations=10`，WS 上一条对应帧都没有。
   修法与回归测试见 CHANGELOG 的 `[Unreleased] → Fixed`。

**实现 Layer 1 时发现的既有缺陷（顺手修掉，否则联网功能等于白做）**

`CognitiveEngine._append_tool_round_trip` 会把工具结果写成
`role="model"` + `metadata.function_call` 和 `role="user"` + `metadata.function_response`。
Gemini 与 Claude 的 Provider 各自正确处理了这两条元数据，但
`OpenAIProvider._build_messages`（DeepSeek / Qwen / OpenAI 都走它）**两个分支都没有**：
前者落进空分支被丢掉，后者被当成一条内容为空的普通 user 消息。结果是这些端点上
**任何"需要回灌结果"的工具都不生效**——模型只能凭猜回答。现在已翻译成标准的
`assistant.tool_calls` + `role:"tool"` 配对消息。

**Layer 2 实际落地时确定的三条约定**

1. `web_search.enabled` 缺省为 **true**（跟随全局开关）。若缺省 false，用户打开全局开关后
   会发现"所有人设都没反应"，把"配置没生效"和"人设不该上网"两种情况混在一起。
   明确要禁的人设（清朝格格、古代剑客）写 false。
2. `style` 是**说法**，不是能力。填了不认识的 style、或写了 `custom` 却没给 `framing` 时，
   退回 neutral —— 规则比风格重要，不能让整段说明消失。
3. `framing` 只覆盖"怎么说出口"，「该查 / 不该查 / 角色自己的世界一律不查」的硬规则
   **永远附加在后面、不可覆盖**。这是安全网：用户不该为了改口吻而意外丢掉防幻觉的出口。

**实现层面的两个取舍（与 5.1 的分工一致）**

1. 工具 `description` 用功能性中文（不提任何角色口吻），角色怎么说出口交给 P2 的角色卡。
2. `facts[].content` **只**返回包好的信封；标题与发布日期不另外以"干净字段"出现，
   否则模型会读到未包装的那一份，信封等于没做。给前端「参考资料」面板看的干净文本
   由 `strip_untrusted_envelope()` 在引擎里剥壳得到，只用于展示、不进模型上下文。

---

## 1. 目标

给数字人加上「查实时信息」的能力，使它从**陪伴型**向**生活助理型**转变，同时**不破坏角色人设的沉浸感**。

具体要求（来自需求讨论）：

- 能联网查资料（新闻、天气、价钱、事实核查等）。
- 可以**随意开关**：不开的时候角色完全不知道自己有这能力。
- 解释方式**写在角色卡里**（「查手机」「掐指一算」「问线人」等），因为芙宁娜只是测试样例，方案必须能兼容尽可能多样化的人设。
- 与现有的人设、情绪、记忆、MMD 动作联动**不冲突**。

---

## 2. 现状核查（已在代码中逐条确认的事实）

### 2.1 关键发现：前端已有一份联网搜索，但对本项目完全失效

仓库里**已经存在**一份质量很高的联网搜索实现：

- `frontend/packages/stage-ui/src/tools/web-search.ts`（约 239 行）——基于 Tavily 的 `web_search` 工具，已经处理好：请求参数校验、结果条数钳制、超时、URL 清洗、以及**防提示词注入**（把网页内容包进 `<untrusted_content>` 标签 + 配套的系统提示声明）。
- `frontend/packages/stage-ui/src/stores/modules/web-search.ts`——保存 Tavily key 的状态。
- `frontend/packages/stage-pages/src/pages/settings/modules/web-search.vue`——设置页（路由 `/settings/modules/web-search`）。
- `frontend/packages/stage-ui/src/stores/llm-tool-resolver.ts:120`——`resolveWebSearchTools()` 负责在「已配置 key」时挂载该工具。

**但它永远不会被执行**，原因在这一行：

```
frontend/packages/stage-ui/src/stores/chat.ts:120
// Cutover to BetterAgent WebSocket Bridge & Python Cognitive Engine
if (typeof window !== 'undefined' && (window as any).__betterAgentWSBridge) {
```

只要 BetterAgent 的 WebSocket 桥存在，前端就**直接把用户的话转发给 Python 认知引擎，自己完全不调用 LLM**，函数提前 return。前端挂载的工具（包括 `web_search`）因此永远不会被调用。

> **结论**：在设置页填 Tavily key **不会有任何效果**。联网能力必须加在 Python 认知服务这一侧。
> 好消息：那份 TS 实现是极好的**参考样板**，请求格式、注入防护、清洗逻辑都可以照抄成 Python 版。

> **已修复（2026-09-11 第二轮）**：上面这条"设置页填了也没用"已被消掉。`frontend/packages/stage-ui/src/components/modules/WebSearch.vue`（路由 `/settings/modules/web-search` 的实体页面）不再读写那个只存 localStorage 的 module store，
改为直连 admin 配置接口：开关与数值落 `config/config.yaml` 的 `tools.web_search`，Key 落根目录 `.env` 的
`TAVILY_API_KEY`，保存即发 `agent.config.reloaded` 热刷新。也就是说"能不能联网"这件事现在**真的能在界面上改**了。
`stores/modules/web-search.ts` + `tools/web-search.ts` 那份 TS 实现仍然留着不动（对本项目依旧无效），只作对照样板。

### 2.2 可以直接复用的基础设施

| 能力 | 位置 | 复用价值 |
| --- | --- | --- |
| 工具基类 | `services/cognitive/tools/base_tool.py` | 新工具只需实现 name / description / parameters_schema / execute |
| 工具模板 | `services/cognitive/tools/campus_kb_tool.py` | 50 行左右的完整范例，含超时与降级 |
| 工具注册 | `services/cognitive/tool_registry.py:25-35` | 加 2 行 |
| 工具门控 | `services/cognitive/cognitive_engine.py:912-920` | 已有「按条件不给模型看某工具」的先例，**每轮重新求值**，天然支持热更新 |
| 引用收集 | `services/cognitive/cognitive_engine.py:1042-1045` | 已有 `search_campus_kb` 的收集逻辑，扩展即可 |
| 引用数据形状 | `shared/schema/payloads.py:147-151` | 是宽松的 `List[Dict[str, Any]]`，**无需改 schema** |
| 引用展示 UI | `frontend/packages/stage-ui/src/components/gadgets/live-caption-overlay.vue:177-198` | 已有可折叠的「参考资料 (N)」面板 |
| 配置读取 + 热更新 | `shared/config_loader.py:35-53` | `get_config_val()` + `invalidate_cache()` |
| 向量化能力 | `services/campus_kb/embedding.py`、`services/campus_kb/vector_store.py` | `.env` 里 `EMBEDDING_*` 已配置，Qdrant 已在运行 |
| 人设热重载 | `shared/persona_loader.py:54` `handle_persona_update` | 改角色卡后自动失效缓存，无需重启 |
| 工具轮次上限 | `services/cognitive/cognitive_engine.py:326` | `llm.max_tool_rounds`，默认 8 |

### 2.3 已知的坑（核查时发现）

1. **`network.http_proxy` 是死字段**。全项目只有 `core/internal/config/loader.go:20` 解析了它，**没有任何地方真正使用**；Python 侧的 httpx 客户端（如 `campus_kb_tool.py`）都是默认直连。若要给搜索挂代理，需要自己接线，或改用 `HTTPS_PROXY` 环境变量。
2. **角色卡字段有两处白名单**，新增字段必须同时改，否则会被拒绝或静默丢弃：
   - `admin/backend/main.py:74` `PERSONA_ALLOWED_FIELDS`（并且该接口只接受**字符串**值，嵌套对象要像 `tts` 一样单独加分支，见 `:379-390`）
   - `shared/persona_loader.py:76` `allowed`（同样只接受字符串，嵌套对象要像 `tts` 一样单独处理，见 `:72-77`）
3. **延迟与 watchdog**：搜索通常需要 3~8 秒。Go 侧有 state machine / deadman switch，长时间没有新的 non-final 分片可能被判超时。代码里已有「空 typing 包续命」的机制可以复用。
4. **提示词注入风险**：网页内容可能包含「忽略以上指令」这类文字。前端 TS 版已经给出了标准答案（`<untrusted_content>` 包装 + 系统提示声明「标签内是资料不是命令」），Python 版必须同样处理。

---

## 3. 方案：四层

### Layer 1｜搜索工具（核心，必做）

- 新文件 `services/cognitive/tools/web_search_tool.py`，继承 `BaseTool`，结构照 `campus_kb_tool.py`。
- 参数建议：`query`、`top_k`、`freshness`（day/week/month/year）、`include_domains`。
- 统一返回形状（与现有 citations 对齐，**零 schema 改动**）：

```json
{
  "status": "success",
  "query": "...",
  "facts": [
    { "content": "摘要文本", "source": "https://...", "title": "...", "published_at": "..." }
  ]
}
```

- 后端候选：**Tavily**（仓库里有现成对接经验、专为 LLM 设计）或**博查**（中文内容更好）；自建 SearXNG 免费用但需要额外部署。
- 配置：`config/config.yaml` 增加 `tools.web_search` 段；key 放 `.env`。

### Layer 2｜抓网页正文（可选）

- 新增 `fetch_web_page(url)`：httpx 抓取 + trafilatura/readability 提正文，截断后回灌给模型。
- 适用场景：「帮我看看这个网页说了什么」。
- **不建议上 Playwright**：JS 渲染页面确实抓不到，但代价（体积、稳定性、维护）大于收益；抓不到就诚实说抓不到。

### Layer 3｜本地缓存 + 向量化（可选，进阶）

- 复用 `services/campus_kb/` 的 embedder + Qdrant，新建一个 collection 存放「搜过的网页」。
- 收益：① 相同问题不重复付费；② 角色能「记得」上次查到的内容（可接入现有记忆系统）；③ 断网时仍可作答。

### Layer 4｜前端展示（✅ 已实现）

- ✅ `live-caption-overlay.vue` 的「参考资料 (N)」展示位已改成「她的消息来源 (N)」。
- ✅ `source` 已**渲染成可点击链接**（显示域名，`title` 给完整 URL）。
- ✅ 角色化措辞已落地，而且更进一步：**搜索进行中**也有一行带呼吸光的提示，
  文案由角色卡 `web_search.searching` 决定（不是前端硬编码的"正在搜索互联网…"）。

---

## 4. 开关设计（两级，建议先做这两级）

### L0 全局开关（这套部署有没有联网能力）

`config/config.yaml`：

```yaml
tools:
  web_search:
    enabled: false          # 总开关
    provider: "tavily"
    api_key_env: "TAVILY_API_KEY"
    top_k: 5
    timeout_seconds: 15
    max_calls_per_turn: 1   # 单轮最多搜索次数，控成本
    daily_quota: 200        # 每日上限（可选）
```

没配 key 时**不注册工具**（与前端 `resolveWebSearchTools` 的 `configured` 门控思路一致）。

### L1 角色开关（这个人设会不会上网）

写在角色卡 `config/persona/<id>.yaml` 的 `web_search.enabled`。例如「清朝格格」类人设应当关闭。

### 落点与生效方式

两级的实际生效点都在 `services/cognitive/cognitive_engine.py:912-920`——那里负责决定「给模型看哪些工具」。

> **设计要点**：门控是在「**给模型看哪些工具**」这一层做的。关闭时模型**根本看不到这个工具**，自然也不会去调。这比「注册了但提示词里说别用」可靠得多。

> **容易踩的坑**：开关状态必须与角色卡联动。若关闭了联网、角色卡却仍写着「不知道就查一下」，模型会在推理链里想调工具、结果发现没有，从而卡壳或硬编。因此 `prompt_builder` 里那段「信息来源」说明，要**根据开关状态决定是否注入**。

### L2 运行时开关（✅ 已实现）

原先判断"需要经过 NATS 热更新绕一圈，属于锦上添花"。第二轮做了，而且事实证明没那么麻烦：
设置页直连 admin 的 `PATCH /api/admin/config`，后台写文件后发 `agent.config.reloaded`，
cognitive 服务热刷新配置 —— **不需要重启 `runner.py`**。
开关本身也做了双重提示：开着但没填 Key 时页面明确警告"模型仍然看不到工具"，
后台不可达时页面转为只读 + 给出直接改文件的确切位置（而不是"看起来能用但没反应"）。

---

## 5. 角色卡字段与预设（解决「多样化人设」的关键）

### 5.1 核心原则：功能性描述与角色化说法**分工**

- **工具的 `description` 保持功能性、静态**（例如「检索互联网实时信息」）→ 保证**触发率**。
- **角色卡里写「怎么说出口」** → 保证**不割裂**。
- 两者在 system prompt 里汇合：模型因为功能性描述决定「要查」，因为角色卡决定「说成掐指一算」。

> 反向教训：把工具 `description` 写成角色口吻会显著降低 function calling 的准确率。角色口吻全部放角色卡。这是同类「角色 + 工具」项目翻车的常见原因。

### 5.2 字段设计（✅ 已实现）

```yaml
web_search:
  enabled: true       # 缺省 = 跟随全局开关
  style: phone        # 预设：neutral | phone | divination | library | informant | oracle | custom
  alias: ""           # 这个能力在角色语境里叫什么；留空用预设默认
  missed: "这个我可真没听说"   # 查不到时的说法（建议必填）
  framing: |          # 可选：整段自定义"怎么说出口"，覆盖预设说法
    当你要查现实世界的信息时……
```

实现位置：`shared/web_search_persona.py`（渲染 + 硬规则）。字符与语义细节见下面的
「Layer 2 实际落地时确定的三条约定」。

### 5.3 六个预设

| 预设 | 说法示例 | 适合人设 |
| --- | --- | --- |
| `neutral` | 不角色化，直说"查一下资料"（**缺省值**） | 没想好，或不想为这一件事设计口吻 |
| `phone` | 掏手机查一下 / 刚刷到的 | 现代日常（芙宁娜即此类） |
| `divination` | 掐指一算 / 让我卜一卦 | 仙侠、玄幻、神明 |
| `library` | 翻翻典籍 / 查查藏书阁 | 学者、法师、古典 |
| `informant` | 问一下线人 / 我托人打听 | 侦探、间谍、江湖 |
| `oracle` | 闭眼感知一下 / 让世界告诉我 | 超能力、灵媒、AI 本体 |
| `custom` | 用户自己写 | 其他 |

每个预设 = 一段 3~5 行的模板，固定回答三个问题：**什么时候查 / 查到怎么说 / 查不到怎么说**。

> **设计意图**：预设保证下限（用户不用会写提示词），`custom` 保住上限（可完全自定义）。

### 5.4 `missed`（查不到的出口）建议必填

没有出口的角色，一定会为了维持「无所不知」的人设而**编造**。奇幻/神明类人设尤其明显。建议默认值直接给一句，并允许角色卡覆盖。

### 5.5 与情绪联动（增强「是她在查」的观感）

- 查之前：`[emotion:think]` + 一个思考动作，并先说一句「稍等，我翻一下」。
- 查到之后：`[emotion:surprised]` 或 `[emotion:happy]`，情绪要连贯。
- 这条同时解决「搜索期间空窗 3~8 秒」的体验问题——**把技术延迟变成演出**。

---

## 6. 改动清单（按文件）

### 后端（Python / 配置）

| 文件 | 改动 |
| --- | --- |
| `services/cognitive/tools/web_search_tool.py` | **新建**：搜索工具本体（含超时、重试、降级、注入防护包装） |
| `services/cognitive/tools/fetch_page_tool.py` | **新建（Layer 2）**：抓正文 |
| `services/cognitive/tool_registry.py` | 注册新工具（约 2 行） |
| `services/cognitive/cognitive_engine.py:912-920` | 门控：关闭时不把工具放进 `tools_schema` |
| `services/cognitive/cognitive_engine.py:1042-1045` | 引用收集：把 `web_search` 的结果并入 citations |
| `services/cognitive/prompt_builder.py` | 注入角色卡的「信息来源」说明（放在 `:131-136` 的知识边界附近） |
| `services/cognitive/prompt_builder.py` | 工具调用前的「先说一句再查」节奏约束 |
| `shared/persona_loader.py:76` | 白名单加入 `web_search`；嵌套对象需像 `tts` 一样处理 |
| `admin/backend/main.py:74`、`:379-390` | 同上（admin 侧白名单 + 嵌套校验） |
| `shared/persona_loader.py:38` | 空白角色卡的兜底字段补默认值 |
| `config/config.yaml`、`config/config.yaml.example` | 新增 `tools.web_search` 配置段 |
| `config/persona/blank.yaml` | 作为模板补上 `web_search` 字段（含注释说明） |
| `.env` / `.env.example` | 新增搜索服务的 key |

### 前端

| 文件 | 改动 |
| --- | --- |
| `frontend/apps/stage-web/src/pages/settings/persona/index.vue` | 新增第 5 个 tab（联网能力） |
| 同目录新增组件 | 预设下拉 / alias 输入 / missed 输入 / 开关 |
| `frontend/packages/stage-ui/src/services/persona-api.ts` | `PersonaPatch` / `PersonaRecord` 类型补字段 |
| `frontend/packages/stage-ui/src/stores/persona.ts` | 本地降级状态与 `compileBasePrompt` 补齐 |
| `frontend/packages/stage-ui/src/components/gadgets/live-caption-overlay.vue` | `source` 为 URL 时渲染成链接；面板措辞角色化 |
| `frontend/packages/stage-ui/src/tools/web-search.ts` | **只读参考，不要改**（它对本项目无效，但可作对照） |

### 第二轮实际改动（Layer 3 / Layer 4 + 设置页）

| 文件 | 改动 |
| --- | --- |
| `frontend/packages/stage-ui/src/components/modules/WebSearch.vue` | **整页重写**：改走 admin 配置接口，开关 / Key / 三个数值项可直接改并保存（不再只写 localStorage） |
| `frontend/packages/stage-ui/src/services/betteragent-admin-api.ts` | 新增 `getWebSearchConfig` / `updateWebSearchConfig` |
| `frontend/packages/stage-ui/src/services/betteragent-ws.ts` | 新增 `ToolActivityPayload` 类型 + `onToolActivity()` + `agent.tool_activity` 帧分发 |
| `frontend/packages/stage-ui/src/stores/modules/betteragent-gateway.ts` | 新增 `toolActivity` 状态；回合结束 / CSM 空闲时兜底清除 |
| `frontend/packages/stage-ui/src/components/gadgets/live-caption-overlay.vue` | 呼吸光提示块 + 来源链接化 + 面板标题角色化 |
| `frontend/packages/stage-ui/src/services/persona-api.ts` | `PersonaWebSearchSettings` 补 `searching` |
| `frontend/apps/stage-web/src/pages/settings/persona/components/WebSearchTab.vue`、`PersonaFieldGuide.vue` | `searching` 输入框 + ⓘ 字段说明条目 |
| `shared/subjects.py`、`shared/schema/payloads.py` | 新增 `SUBJECT_TOOL_ACTIVITY` / `ToolActivityPayload` |
| `shared/web_search_persona.py` | 7 个预设补 `searching`；新增 `render_web_search_activity_label()` |
| `services/cognitive/cognitive_engine.py` | 搜索前后各发一条 `ToolActivityPayload` |
| `services/cognitive/main.py` | 路由 `ToolActivityPayload` → 发布到 `SUBJECT_TOOL_ACTIVITY` |
| `core/internal/bus/nats_bus.go`、`internal/schema/payloads.go`、`internal/webgateway/protocol.go`、`internal/webgateway/nats_bridge.go` | Go 侧镜像 + 转发为 `agent.tool_activity` WS 帧 |
| `admin/backend/main.py` | 白名单补 `searching`；配置写入改用 LF（`newline="\n"`） |
| `shared/persona_loader.py` | 白名单补 `searching` |
| `config/persona/furina.yaml`、`config/persona/blank.yaml` | `searching` 字段 + 注释模板 |
| `tests/test_web_search_tool.py` | 引用收集的断言改为按"有没有 citations"挑（新增的进度事件不带 citations）；补 start/done 顺序断言 |
| `tests/test_persona_web_search.py` | 补 `render_web_search_activity_label` 的覆盖（预设默认 / 单字段覆盖 / 人设关闭时为空） |

---

## 7. 风险与不确定性（按严重程度排序）

1. **触发率（唯一真正的不确定性）**。当前 provider 是 `deepseek-flash`。若它在中文口语提问下不肯调工具，后续所有工作都没有意义。缓解：功能性 `description` + 角色卡硬规则 + 日志打印「本轮是否决定搜索」；若仍不行，**换更强的模型**比继续调提示词更省事。
2. **延迟与节奏**。搜索 3~8 秒，TTS 是分段播报，期间会空窗；Go 侧有超时判定。缓解：先说一句再查（见 5.5）。
3. **网络可达性**。Tavily 在中国大陆一般可连但偶尔慢；Google/Bing 官方 API 基本不可用。且 `network.http_proxy` 目前是死字段（见 2.3），要走代理由自己接线。**必须实测。**
4. **提示词注入**。必须照抄 TS 版的处理（`<untrusted_content>` + 系统提示声明）。否则一个恶意网页即可让角色「越狱」。
5. **幻觉未根治**。搜到 ≠ 用对。角色卡必须写死「只根据查到的内容回答，结果里没有就说没有」，并显式禁止「把查到的讲成我亲历的」。
6. **成本与滥用**。每次搜索 = 1 次第三方调用 + 可能多 1 轮 LLM。需要 `max_calls_per_turn` 与每日配额。

---

## 8. 工作量与建议顺序

### 估算（按可交付粒度）

| 阶段 | 内容 | 估算 |
| --- | --- | --- |
| P1 | 工具 + 后端对接 + L0/L1 开关 + 注册 + 引用收集 | 0.5 天 |
| P2 | 角色卡字段（两处白名单 + prompt_builder）+ 6 预设 + 模板 | 0.5 天 |
| P3 | 前端设置页 tab + 引用链接化 | 0.5~1 天 |
| P4 | 抓网页正文（可选） | 0.5~1 天 |
| P5 | 本地缓存 + 向量化（可选） | 1~2 天 |
| P6 | 单元测试 + 文档 + 配置样例 | 0.5 天 |
| | **P1~P3 + P6（建议的最小完整集）** | **约 2~3 天** |
| | **全四层** | **约 4~6 天** |

注：以上为纯产出速度，不含来回实测的时间；触发率调优通常另需 1~3 天，且需要维护者本人参与。

### 建议顺序（重要）

1. **先只做 P1 的最小版**（一个 `web_search` 工具 + 一个硬编码的「查手机」说法），**不做**人设包装。
2. 用真实 key 聊几句，观察触发率。**这一步不到半天，却能避免后面几个阶段白做。**
3. 触发率可接受 → 继续 P2、P3。
4. 触发率不可接受 → 先考虑换模型，而不是堆提示词。
5. 以上都稳定后，再评估 P4 / P5。

---

## 9. 无法在当前开发环境验证的部分

实现过程中，以下内容**必须在维护者本机验证**：

1. **真实联网**：当前执行环境网络受限（连本地端口都会被拦截），无法真正调用搜索服务。真实 API 连通性、返回格式、代理是否生效都需要本机实测。
   - 对策：工具写成「key 缺失 / 请求失败时优雅降级 + 打清晰日志」，填上 key 一测即知。
2. **触发率**：必须靠真实对话反复试，无法离线闭环。
3. **延迟体感**：「先说一句再查」的节奏是否舒服，需要维护者实际听/看。

可以在当前环境完成并自测的部分：工具行为（用 mock 后端）、门控逻辑、提示词注入、预设渲染、前端类型检查、单元测试。

---

## 10. 待决策问题

1. 搜索后端选哪一个？（Tavily / 博查 / 自建 SearXNG）——需要先去申请 key。
2. 是否接受「先做 P1 验证触发率，再决定是否继续」的顺序？
3. 前端运行时开关（L2）现在做还是以后做？**建议以后。**
4. 是否需要 Layer 2（抓正文）和 Layer 3（缓存/向量化）？还是先只做 Layer 1？

---

## 11. 其他收尾事项（与联网无关，但同样待处理）

### 11.1 猫娘人设清洗：代码已改完，**尚未在运行环境验证**

已完成的改动（离线验证通过）：

- 内置默认人设由「猫娘 Camelia」改为新建的**空白角色卡** `config/persona/blank.yaml`。
- `config/config.yaml` 新增 `persona.default_user_name: "旅行者"`，并清空残留的 Camelia 名字/外形字段。
- `config/persona/furina.yaml` 写明称呼为「旅行者」/「肉丝拌川」，并禁止使用「主人」。
- 「公文」类生硬说法改为「据我所知」「听人说起过」「年代太久记不清了」。
- Go 内核每轮注入的 `[猫娘内心状态]` / `[猫娘性格设定]` 改为中性标签，并**已重新编译** `bin/betteragent_core.exe`。
- 清洗了 `services/companion/companion.db` 中遗留的 `用户称呼 = 主人` 记录。
- 前端设置页的猫娘文案与默认值（称呼「主人」、句尾词「喵~」、Camelia 提示词）改为中性，并加入**一次性 localStorage 迁移**。

**待办（需要人在场）**：

1. 重启服务：`cd /d D:\college\2027qiu\数字人\BetterAgent-main\BetterAgent-main` 然后 `python runner.py`。
2. 浏览器 **Ctrl+F5 强刷**一次（触发前端的一次性迁移，清掉旧的「主人 / 喵~」本地存储）。
3. 聊一句确认「主人」已消失；若偶发复现，多半来自历史会话记录，可在管理端清一次会话。

**已决策（2026-09）**：`config/persona/catgirl.yaml`、`patra.yaml` 已删除；内置示例人设只保留 `blank.yaml`（白板）与 `furina.yaml`（当前 active）。前端设置页会自动对齐系统激活人设，不再默认停在 blank。

### 11.2 MMD 表情：`smile` 首选到了闭眼笑（未修改）

- 现象：做完动作后「眼睛眯起来」。
- 原因：`frontend/packages/stage-ui-mmd/src/constants/morphs.ts:52` 的候选表为
  `smile: ['笑い', 'にこり', 'わらい', 'smile', 'Smile']`，**取第一个存在的**。而芙宁娜模型的 `笑い` 属于 **[eye] 类（闭眼笑）**，所以变成了眯眼。
- 建议修复：把纯嘴部形变 `口角上げ`（嘴角上扬）加入候选表并提到首位，或按模型分类分别配置。
- **当前状态：未修改**，待决策。

### 11.3 前端 `startVision` 未使用告警（既有问题，非本次引入）

`frontend/apps/stage-web/src/components/VisionPrivacyIndicator.vue:9` 的 `startVision` 声明后未使用，类型检查会报 TS6133。属于既存问题，与本次改动无关。

### 11.4 角色卡 `personality.*` 目前没有被内核读取（未修复）

- 现象：`config/persona/*.yaml` 里的 `personality:` 段（`tsundere_level`、`clinginess`、
  `jealousy_threshold`、`cat_nature`、`neuroticism`、`extraversion`）改了没有任何效果。
- 原因：Go 内核启动时直接用的是内置默认值 —— `core/cmd/main.go` 的
  `emotion.DefaultPersonality()`。`emotion.NewPersonalityFromConfig()` 只在单元测试里被调用过，
  没有任何生产代码路径读取角色卡的这一段。
- 现状：真正影响对话的是设置页「性格权重」滑杆 —— 它把 `【傲娇权重】/【粘人权重】`
  编译进 base_prompt 头部，是生效的；YAML 里的数值目前只起"文档/意图声明"作用。
- 影响面：前端「角色卡字段说明」面板已如实标注"⚠ 当前未生效"，避免用户白调。
- 若要修复：在 Go 侧启动时读 `config/persona/<active>.yaml` 的 `personality` 段传给
  `NewPersonalityFromConfig`（并考虑人设热切换时重新加载），属于独立的小改动。
