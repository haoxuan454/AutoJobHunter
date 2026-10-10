# AutoJobHunter 低频自动化验收记录（2026-10-10，上海时区）

本文是持续更新的证据记录，不是“全部通过”声明。只使用主会话；修改前备份，不触碰凭据、用户简历和浏览器登录资料。手动流程必须保留。

## 最新结论（优先于下文历史阶段记录）

2026-10-10 重新启动后的验收正在进行：8686 监听 PID 37584，启动时间为上海时间 14:25:45，当前工作台无活动任务；真实预检通过且模型仍为 deepseek-flash。旧 PID 39588 的未重载阻塞已由用户正常重启解除，但完整自动验收结果仍须以下新阶段证据确认，不能仅由进程变化推定全部通过。

### 重启后验收矩阵（执行前登记）

| ID | 场景 | 方法及通过信号 | 当前状态 |
| --- | --- | --- | --- |
| RESTART-01 | 最新首页入口 | 新 PID、磁盘时间、首页 DOM、预检及真实 auto_full 任务 | PID/预检已核，任务待启动 |
| AUTO-NEW-01 | 双平台并行采集 | 首页选择数据分析/东莞/1 页；分别有独立采集 run_id 和新岗位 | 待执行；不清除历史断点 |
| AUTO-SCORE-01 | 真实评分与筛选 | deepseek-flash，阈值 60，每平台最多 2 个；任务评分轨迹对应本轮 | 待执行；不制造分数 |
| AUTO-SEND-01 | 串行低频投递 | BOSS 您好，智联平台默认；60～180 秒；平台原文与库/API/日志一致 | 待执行；不自动重试不确定发送 |
| AUTO-CARD-01 | 本轮身份与会话 | 各样本岗位、公司、HR、会话映射、全局活动排序和上海时间 | 待执行；新旧账号不混合 |
| AUTO-LOOP-01 | 持续监控而非任务结束 | 同一 auto_full 任务进入监控，真实循环范围仅本轮已验证会话 | 待执行 |
| AUTO-REPLY-01 | 新 HR 自动回复 | 真实合适 HR 新消息、资料来源、发送快照、原文送达和幂等 | 待真实触发，不能伪造 HR 回复 |
| AUTO-STOP-01 | 单卡停用与敏感接管 | 用户禁用后下一轮跳过，敏感词暂停并可靠通知 | 待执行；邮件排队不冒充送达 |
| AUTO-DATA-01 | 合成/原生消息双表示 | 建立身份、原生 ID、发送时间可靠关联，再测同步幂等 | 仍待处理，禁止按文本粗删 |


README 已按 AutoJobHunter 当前代码重写，包含真实本地截图、安装配置、自动/手动链路、队列、安全边界、架构、数据隔离及明确的验收缺口。没有执行 GitHub 提交或推送。

“不能宣称全部通过”不是说两个平台完全不能用，而是下面几个必要条件尚未同时成立：

1. 8686 服务仍为 PID 39588，启动时间 2026-10-10 10:25:41；本轮最新修复尚未在该入口重新加载。正常重启被工具执行策略拒绝，没有改用其他终止手段绕过，也没有把另起进程当作根页面入口复验。
2. 最新代码已经完成两平台已验证样本的两轮真实只读同步，但不是从首页点击 `auto_full` 到 AI 回发的完整新一轮证明。每平台 2～3 个独立岗位的真实证据仍不足，不能用计数器或重复读取凑样本。
3. BOSS 已验证样本暂时只有用户消息；智联已验证样本的 HR 回复为不匹配/拒绝。不向拒绝岗位补发，也不伪造 HR 消息，所以合适的新消息触发 AI 自动回发的真实送达尚未验收。
4. BOSS 原生消息 ID 接入后，历史 `send:` 合成发送记录与后来平台原生记录存在同文双表示；旧无 ID 消息迁移已修，合成记录与原生记录的安全归并仍待验证。不得按文本粗暴删除或改写自动回复幂等键。

以下“本轮运行记录”“第三轮”等是按时间保留的历史证据，某阶段曾待修不代表当前仍未修；以本节和文末最新修复/复验为准。测试成功、HTTP 成功、SQLite 写入和实际平台送达分别记录。

## 验收边界

- 首页唯一入口 `auto_full`：BOSS/智联并行采集 → 本轮评分 → 阈值筛选 → 平台内串行投递 → 已验证成功会话补齐 → 持续低频监控 → AI 结合资料回复。
- 测试阈值 60、各平台第一页、关键词 python、城市东莞；首轮每平台最多 1 个，成功后才扩大至 2～3 个；间隔 60～180 秒。BOSS 测试消息限“您好”；智联首次招呼使用平台默认话术。
- 保持 deepseek-flash，不替换模型、不伪造评分、消息、HR 回复或发送证据。
- 成功必须同时有平台页面、SQLite、API、运行日志、Web UI 证据。缺少真实 HR 回复时，自动回复的真实验收仍待外部条件，不以离线测试冒充。
- 新旧平台账号可能不同；禁止通过放宽身份验证把旧会话错配到新账号。

## 场景矩阵

| ID | 场景及用户行为 | 验证方式 | 期望 | 当前事实与状态 | 清理 |
| --- | --- | --- | --- | --- | --- |
| LOGIN-01 | Chrome 登录正常，但页面含隐藏登录控件/广告 | 本地 Chrome 六组 DOM fixture + 真实 preflight + auto_full 采集 | 非登录墙不报未登录，真正登录弹窗阻断 | 六组 fixture 通过；智联真实采集新增 28 条；历史误报具体 DOM 未保留，不能断言历史唯一原因 | fixture 页已关闭 |
| QUEUE-01 | 同时操作三个积压面板 | BacklogPanel + DashboardBacklog 集成测试、真实首页 DOM | 固定高度内部滚动，选择独立，单删/批删/全选回收 | 16 个相关前端测试通过；真实三个框 clientHeight 358px，scrollHeight 569/4738/4916 | 未删除真实积压 |
| QUEUE-02 | 取消、重复点击、后台任务冲突、实际删除 0 条 | DashboardBacklog.test.tsx | 取消无请求；删除中锁定；409 保留卡片；0 不谎报成功 | 通过；数据库使用软删除，可恢复 | 持久回归测试保留 |
| AUTO-01 | 双平台并行真实采集 | task 07bf079e-0e79-4e16-a027-194b3920a539 | 两平台采集各自完成 | BOSS seen 15/new 4/duplicate 9/filtered 2；智联 seen 37/new 28/duplicate 9 | 岗位留在岗位池 |
| AUTO-02 | 平台列表预筛丢弃岗位后评分 | 真实任务 + CollectionOrchestrator 回归 | 未入库候选不得进入评分范围；真正缺失仍 fail-closed | 修复后第二轮评分完整性通过；13 个 scorable，1 个已处理跳过；第一轮的泄漏不再阻断 | 第一轮没有平台发送 |
| SORT-01 | 历史消息晚入库、跨时区时间、新回复位于第 5 页 | ConversationRepository + ConversationPagination 回归、真实 Chrome 页面 | 全量按真实消息时间排序，再分页；频率规则同样全局 | 后端三项排序回归通过；60 卡片 fixture 第 5 页新会话同步后升至第 1 页；真实 21 卡片 recent/frequency/created 各两页逐项匹配全局 API 顺序 | 没有同步或修改真实聊天；临时本地页面已关闭 |
| SORT-02 | 快速切换排序、删除尾页最后卡片 | ConversationPagination 动态 React 测试 | 旧响应不得覆盖新排序；页码自动收敛 | 四项分页动态测试通过，包括每页数量、尾页删除和旧响应竞争；真实页面每页 12/24 验证通过 | fixture 仅内存；未删除真实会话 |
| AUTO-03 | 达标投递、页面确认、本地会话补齐 | 五层真实证据 | 没有人工确认环节；确实送达且不串会话 | 智联默认招呼和 HR 拒绝已补平台 DOM 证据；BOSS 样本“您好”可读取。各平台目前各一个已核页面样本，不把历史 succeeded/reconciled 计数解释成 2～3 个独立岗位全部通过 | 不重复投递本轮岗位 |
| AUTO-04 | 持续轮询、HR 回复、资料生成回复 | 真实监控 + 测试 | 只处理本轮已验证会话、敏感问题人工接管 | 最新代码独立进程两轮真实同步均 processed 2/failed 0；未启用自动回复，new_hr_messages 0，真实 AI 回发仍未获合适触发，不能称完整通过 | 临时平台页已关闭；不伪造 HR 回复 |
| ADV-01 | 越权/串会话/提示词注入/伪成功 | 自动监控、发送安全、资料隔离回归 | 身份不明不得发送，不因 HTTP 200 宣称送达 | 需汇总后续测试证据 | 离线 DB fixture |
| ADV-02 | 停止/恢复/异常/旧状态/超时 | runner 与 monitor 回归 | 不重复发送、不放宽安全校验、等待有上限 | 需汇总后续测试证据 | 不停止用户浏览器 |
| BUILD-01 | 前端全量与生产构建 | npm run test -- --run；npm run build | 测试及类型检查通过 | 最终 14 files / 46 tests passed，tsc 与生产构建退出 0；dist index-IOGkndVu.js；仅 chunk-size、ReactRouter future 与测试 DOM 尺寸警告 | 构建产物用于服务 |

## 问题及修复记录

1. 智联登录误判风险：隐藏弹窗/整页登录文案/普通 role=dialog 不等于登录墙。diagnostics.py 和 zhilian.py 统一要求登录控件可见，泛 dialog 必须有登录文本。当前真实 preflight 和采集证明此轮登录有效；不把没有历史 DOM 的推断写成定论。
2. 评分范围泄漏：`_SharedProcessor.inspect()` 提前加入未落库候选；BOSS 在它之后执行平台预筛，会丢弃匿名公司岗位，导致评分报告 missing。把新岗位加入 matched_job_ids 的时机移到成功 save 后；已有重复岗位仍保留在本轮范围，评分端继续拒绝真正缺失/无效 trace。
3. 最近活跃排序：原优先采用全局 SQLite 消息 ID，晚补的历史消息会错误置顶。复用完整聊天最新消息的选择规则，以绝对消息时间排序；缺平台绝对时间时使用该消息首次本地到达时间，不用同步时间。前端取得全量排序后才分页，默认每页 12，可选 24/48。
4. 前端删除虚报与重复提交：affected_count 为 0 时不应 fallback 到请求条数；使用 nullish fallback 并增加提交锁及按钮禁用。
5. BOSS 岗位相对地址：第二轮发送器直接把 `/job_detail/...` 交给 Chrome，真实只读对比中落到 about:blank；相同路径补齐 BOSS 域名后岗位页可见“立即沟通”，未点击。新增独立 `boss_urls.py`，采集和发送共用安全地址解析，保留 identity query，拒绝外域、非详情路径和危险 scheme。采集详情页使用解析后的地址，避免二次拼接域名；旧数据库相对地址也在发送入口补齐。不改智联发送代码、不放宽 HR 身份校验。
6. 智联第二轮没有新增采集并非登录失效：关键词/城市组合已在 24 小时 checkpoint 内完成，因此 seen 0。保留安全 checkpoint，后续真实复验不得把缓存跳过当作新采集成功。

测试装置错误单独归类：无 jest-dom 的 toBeChecked、重复 notice 文本、多余 status 查找、evaluate 参数反序及返回值可能为字符串/对象。均先修装置后运行真实断言，不归类为平台故障。

## 本轮运行记录

- task `07bf079e-0e79-4e16-a027-194b3920a539`，2026-10-10 09:57:41 开始，10:00:53 停止于 scoring_incomplete。
- new 32，scorable 47，eligible 2，approved/attempted/succeeded/reconciled 均 0；不能写为投递闭环成功。
- 47 个评分均有同一 `_automatic_run_id` 的有效 V1 评分 trace。models 预检不等于评分调用，实际 trace 才是本轮评分证据。
- 第二轮 task `699ab3da-82cb-4ca6-a077-2f7452380b1c`：2026-10-10 10:12:12 开始，约 10:13:55 停止于 delivery_not_safely_verified。BOSS seen 15/new 0/duplicate 14/filtered 1；智联 seen 0（已完成组合 checkpoint）。scorable 13，handled/skipped 1，eligible/approved/attempted 各 1，succeeded 0，failed 1，reconciled 0；目标数谷智能 Python，失败原因 no_chat_button。投递没有通过，监控未启动。
- 本轮 Python 分组回归：会话排序、采集编排、自动评分、全流程、登录诊断、智联采集、自动监控、分析等 219 passed / 5 subtests passed；BOSS URL、采集、岗位选择、平台发送、元数据 147 passed / 6 subtests passed。分组有重叠，不累加冒充全量独立测试；不是 Python 全量结果。
- 真实本地 Chrome 分页：总 21 卡片，第 1 页 12、第 2 页 9；recent/frequency/created 三组每页卡片 ID 均逐项匹配全局 API；每页 24 展示全部 21。没有请求招聘平台同步，没有真实删除。
- BOSS URL 修复备份：`.codex-backups/autojobhunter-boss-url-20261010-1017`；评分范围修复已加载，地址修复的运行时加载与真实复验另记，不把磁盘改动等同于实际送达。
- 备份：`.codex-backups/autojobhunter-boundary-20261010`、`.codex-backups/autojobhunter-pagination-scope-20261010` 及前序备份。保留回退路径，不递归删除任何目录。
- 当前用户禁止子会话：独立双代理审查未进行，不宣称 independent review 或 merge approval。
- OMX 状态工具未安装，不伪造 OMX 生命周期状态；以本文和实际任务状态跟踪。

## 后续放行条件

排序、分页和前端构建已通过，最新采集地址改动还需最终回归并精准加载后端。不要反复运行已完成的关键词/城市组合，也不清安全 checkpoint。后续自动入口保持同样低频边界、真实评分和任务 ID；每平台首个投递必须核验真实页面，之后才能扩大样本。若遇到验证码、登录失效或身份不明，立即停止对应平台，不绕过。

分页实现当前为 API 全量排序、前端分页渲染，而非数据库分页；不会只排序当前页。会话数量非常大时，全量传输及现有逐会话查询仍有性能边界，不能宣称无限规模已验收。

## 第三轮真实任务及最终回归（续记）

- 地址修复加载：安全重启前核实无运行任务，8686 实际 listener 为 PID 39588；旧日志已备份，不停止 Chrome/runtime。
- BOSS URL 与 collector 最终回归：52 passed，6 subtests passed，101.05 秒。
- 手动流程保护回归（small_fixes/platform_delivery_guard/send_windows/human_delivery_guard）：81 passed，9 subtests passed，5.62 秒。两条旧源码字样断言改为共享 BacklogPanel 对应行为；补回筛选空列表提示，新增隐藏旧选择不得批删及自定义空提示动态测试。不改变发送安全边界。
- 最终前端：46 tests / 14 files passed；生产构建成功。以上分组有重叠，不累加冒充 Python 全量通过。
- 第三轮 task `2be5ca50-fb50-42bc-ae77-6ee2994de8b4`：首页 `/api/workbench/task` 一次 POST，mode=auto_full；双平台 python/广州，各一页，真实评分阈值 60，各最多投递 1 个，间隔 60～180 秒，BOSS 内容“您好”。换城市用于合法新组合，不清东莞 checkpoint。
- BOSS seen 15/new 9/duplicate 4/filtered 2；智联 seen 17/new 10/duplicate 7；29 个 scorable，1 个已处理跳过。auto_collected 19，eligible/approved/attempted/succeeded/reconciled 各 2，failed 0。
- 进入 monitoring 后安全停止：status=stopped，stop_reason=sync_not_loaded；processed 1、failed 1、新 HR 消息和自动回复均 0。失败会话 `boss:delivery:00be551d1430b71cf517dc14`。任务计数和数据库 sent 不等于五层真实送达或持续监控验收完成，禁止重复发送同一“您好”。
- BOSS 麦东信息技术/python开发工程师(兼职)，评分 69：岗位与会话 HR 字段包含“陈维”和“半年前活跃”；external_conversation_id 为空，仅保存通用 chat 收件箱地址。姓名 DOM 子节点污染待验证，不能直接放宽 identity scorer。
- 智联 广州埃浮盛网络科技有限公司/python数据分析师，评分 81，HR 侯小慧；会话 `zhilian:delivery:57fac93cb085386e855f6d57`。本段仍需只读确认实际平台消息，不重投。
- 本段继续时只读获取 Chrome targets：智联 IM 页存在，BOSS 仅搜索页，没有聊天页。自动发送器关闭临时聊天页后，监控只读已打开面板无法找到新会话；需修正自动链路会话加载生命周期，而非弱化身份校验。
- 下一步：一次低频读取真实平台聊天页面确认首个样本实际送达；修上游姓名解析和安全会话加载后复验监控。没有真实 HR 回复时，不伪造自动回复闭环通过。

## 分页最新运行时复验与平台只读核对

- 8686 `/conversations` 返回 200，HTML 引用最新 `index-IOGkndVu.js`。在当前真实 Chrome 新建本地测试页读取最新 23 个会话：最近活跃/对话最频繁/创建时间三组，第 1 页 12、第 2 页 11，六次页面卡片 ID 均逐项等于 API 全局序列的切片；改为 24/页后全部 23 个顺序同样匹配。没有点招聘平台同步或删除真实卡片。
- 会话与投递映射本段补跑：`pytest tests/test_conversations.py tests/test_conversation_bridge.py -q --tb=line`，37 passed，退出 0。
- 分页验收已完成：全量排序先于分页；新内容同步后回第一页；每页数量/末页删除/旧响应竞争有动态回归。第 5 页新消息升第 1 页使用 60 张内存 fixture，不往真实数据库制造消息。
- BOSS 单次打开聊天收件箱，只读列表 40 行，其中唯一“陈维/麦东信息技术”行的 last_message 为“您好”。坐标选择没有通过 active 校验，返回 chat_open_not_verified；没有继续发送。随后对唯一姓名+公司 DOM 行进行一次直接点击，active 校验通过，目标聊天提取到包含“您好”的 me 消息。该证据说明坐标点击与 DOM 点击表现有差异，需要后续单独修复并补测试；不能把探针的直接点击冒充生产选择器已修。
- 探针错误单独记录：PowerShell 默认 stdin 编码使中文 aria-label 变成问号；显式 UTF-8 后同一纯本地探针通过。属于装置编码问题，不是页面故障。
- 清理：本段只关闭自己创建的本地分页页与 BOSS 核验页；不关闭用户原有页面，不终止 Chrome，不重启服务，不修改已发送状态，不清 checkpoint。
- 自动链路当前仍未达到全部验收：姓名污染、聊天页生命周期及安全选择器需修；智联真实消息证据和持续监控/真实 HR 回复后的自动回发仍待完成。本次分页通过不等于自动流程全部通过。

## README 迭代后的修复与实测（最新阶段）

### 已修复的问题及原因

| 问题 | 根因 | 模块化处理 | 已有证据/边界 |
| --- | --- | --- | --- |
| 投递完成后监控找不到聊天页 | 发送器结束会关闭自己的临时页，监控此前只读已打开页 | `automation/chat_pages.py` 为自动任务保有自己的收件箱页，复用用户页但不导航/关闭用户页；最多一次打开，加载有界 | 页面所有权、丢失、跳登录、超时、停止、about:blank 就绪误判有回归；两个平台真实同步两轮成功 |
| BOSS HR 名称含“半年前活跃” | 岗位页聚合文本将活跃标签并入姓名 | `collection/recruiter_identity.py` 只清已知、空白分隔的完整活动后缀，采集与投递映射复用 | 不对正常人名或公司子串模糊删改；真实样本姓名为陈维 |
| BOSS 坐标点击无效/读到旧正文 | 列表选中不等于目标消息面板加载完成 | `platform_delivery/boss_chat_selection.py` 唯一行定位、一次 DOM 点击兜底，并验证活动身份、目标正文身份和 loading | 生产选择器真实返回 matched_chat_loaded；本地真实 Chrome 异步正文 fixture 验证旧正文不能通过 |
| BOSS 叶子消息提取不完整、没有 ID/时间 | 旧选择器读聚合父节点，混入回执/重复文本 | `executor/monitor.py` 按消息叶子提取，优先 text-content，读取原生 ID/时间；`boss_snapshot.py` 同会话旧无 ID 行一对一迁移 | 原生两条 outgoing 可读；不把不同平台 ID 合并；历史合成发送记录的双表示仍待处理 |
| AI 生成过程中用户/HR 继续发消息 | 只检查本地库不能发现尚未同步的平台变化 | `automation/snapshot_guard.py` 在安全选中目标后重读平台快照，再决定是否调用已有手动发送适配器 | 两平台共享适配器的动态测试覆盖新 HR、手动回复、同文不同 ID、不可读、系统回执；变化时发送未开始 |
| 自动回复缺随机等待或重复发送风险 | 生成后直接发送缺少重新核验/持久认领 | `automation/reply_dispatch.py` 可取消等待、重核身份/开关/状态/本地上下文、认领幂等键、真实验证后才落库 | 60～180 秒等待、停用、暂停、身份变化、结果不明、异常、重复发送有回归；未证明真实 AI 回发 |
| AI 临时失败后漏掉已同步问题 | 下一轮 inserted 为 0，原实现丢弃触发 | `automation/monitor.py` 任务内保留待处理问题，成功/人工回答/接管才清 | 跨轮失败恢复有回归；这是内存待处理，不是跨进程自动恢复 |
| 生成新草稿后永久哈希冲突 | 未发送旧草稿占用相同 HR 触发的幂等键 | 仓库新增默认关闭的 `replace_unsent_hash`；仅自动调用允许原子替换 not_sent 草稿 | 实际 SQLite 生命周期通过；pending/unknown/sent 不重开；手动默认冲突规则不变 |
| 30 分钟配置实际等待 45 分钟 | 轮询间隔被采集延迟系数再次乘大 | 监控间隔使用 monitor.interval 本身；非有限/非法值回落默认 | 配置30与节流系数1.5仍为30；NaN/Infinity 等覆盖；页面操作节流不改 |
| 非有限自动参数进入任务 | clamp 之前没有 finite 校验，nan/-inf 阈值可能折为0 | 自动入口在预检/入队前拒绝 NaN、无穷与布尔数值 | 12项临时 DB/WSGI 恶意参数测试先红后绿；拒绝时无任务、无配置落盘、无 AI 或平台操作 |
| 旧 full 测试与已删除入口矛盾 | 测试仍期待旧手动确认流，品牌测试仍期待 BossHunter | 有效任务用 auto_full；旧入口测试改为410拒绝、不能落盘/执行；旧任务确认 API 保持409拒绝 | 未恢复旧 full；未加 skip/xfail；保留“不执行/不污染设置”的真实断言 |
| BOSS 通用收件箱被显示成 HR 专属链接 | 泛化 /web/geek/chat 被接受为具体链接 | 具体会话链接必须具有实际非空线程标识；未获地址隐藏按钮 | 不伪造 BOSS HR 深链，不改变智联具体链接规则 |

### 两轮真实平台只读监测

使用导入最新代码的独立 Python 进程，限制 `verified_delivery_scope` 为下表两个已经送达并核对身份的会话，关闭自动回发。两轮相隔 60 秒，没有重复投递/补发，没有直接调用平台私有 API。

| 平台 | 目标与身份 | 平台 DOM / 本地结果 |
| --- | --- | --- |
| BOSS | 麦东信息技术 / python开发工程师(兼职)，真实评分69，HR 陈维；boss:delivery:00be551d1430b71cf517dc14 | 安全生产选择通过；读取2条 outgoing、2个原生 ID/时间，平台可见“您好”；本地历史合成记录双表示仍存在 |
| 智联 | 广州埃浮盛网络科技有限公司 / python数据分析师，真实评分81，HR 侯小慧；zhilian:delivery:57fac93cb085386e855f6d57 | matcher 唯一匹配，读3条平台消息，确认默认招呼及不匹配/拒绝回复；该回复不用于强行自动回发验收 |

两轮结果均为：processed 2、skipped 0、new_hr_messages 0、handed_off 0、replied 0、failed 0、scope_valid true；两平台详情均 status synced、inserted 0、new_hr_messages 0。任务创建的临时页已关闭，用户原页未关闭。该证据证明修复后的真实读取链路，不等于根入口新任务或 AI 回发通过。

### 最新 QA 场景补充

| ID | 意图/异常输入 | 执行证据 | 实际结果 | 清理/保留 |
| --- | --- | --- | --- | --- |
| ADV-SNAPSHOT | AI 后出现新 HR、手动消息、同文不同原生 ID、不可读 | test_automatic_snapshot_guard.py，调用两个真实适配器的控制流，浏览器接口受控 | 未开始发送；系统回执不误作消息变化 | 持久回归测试保留，未发平台消息 |
| ADV-CANCEL | 随机等待中停止，用户停用/暂停，目标平台/岗位/用户变化 | test_automatic_reply_dispatch.py | 取消/状态/身份检查不触发发送 | 临时内存库销毁 |
| ADV-CLAIM | not_sent 后重生成，pending/unknown/sent 后重复请求 | 真实 SQLite 仓库及自动调度生命周期 | 可安全重新生成未发稿；不重开可能已发/已发状态，手动规则不变 | 持久测试保留 |
| ADV-PAGE | 页面丢失、跳转登录、about:blank、超时、用户已有页 | test_automatic_chat_pages.py | 限次打开/有界等待，不反复开页，不关闭用户页 | 受控浏览器调用，无平台网络 |
| ADV-PARAM | nan/inf/-inf/True × 阈值/等待上下限 | /api/workbench/task 真实本地 WSGI + 临时 DB | 原12项失败，修后12项通过；拒绝在 preflight 前发生 | 无真实数据改写 |
| ADV-RETRY | AI 失败/分类异常后继续一轮 | test_automatic_conversation_monitor.py | 未答问题保留，人工回答后清除；不伪造新消息 | 任务内存 fixture |
| QA-DIRTY | 已有未提交修改、截图、备份 | git status / diff 检查 | 保留用户原有改动，备份仅精确文件，不 reset/清历史 | .codex-backups 保留回退 |
| QA-LIMIT | 无真实合适 HR 回复、旧服务未重载、禁用子任务 | 两轮真实 DOM + PID + 执行拒绝记录 | 阻塞项明确，不以成功字样/离线测试代替送达 | 未终止用户服务/Chrome，独立审查不可用 |

### 测试与装置故障记录

- 第一轮 Python 全量：16 failed、1424 passed、98 subtests passed，380.42 秒。主要为旧 full/品牌断言，不是全部绿；随后迁移为当前入口及明确拒绝旧入口的回归。
- 新回归曾漏导入 Mock：2 failed、136 passed；补导入后 test_web_api_routes.py 为138 passed、45 subtests passed。该项是测试装置问题，不是平台发送缺陷。
- 启动参数缺陷先复现12项失败，再修finite校验；启动/评分上限、API、预检三组最终176 passed、45 subtests passed，58.53秒。
- 自动回复调度、仓库、回复 API 三组64 passed，16.77秒；监控安全相关37 passed、8 subtests passed。分组重叠，不相加当全量。
- 本阶段前端全量14 files / 46 tests passed，19.20秒；tsc + Vite 构建退出0，产物 index-IOGkndVu.js；有 ReactRouter future、测试 DOM 尺寸及 chunk-size 警告，不报作构建失败或隐藏。
- 本阶段最终 Python 全量：`pytest -q --tb=short`，1460 passed、111 subtests passed，377.60秒，退出0。没有靠恢复旧full、添加skip/xfail或伪造平台数据变绿；这是代码回归通过，不是双平台真实全量验收通过。
- README 三张截图及本地链接全部存在；最终 git diff --check 和改动模块 compileall 均退出0。README 以 AutoJobHunter 为产品名，内部 bosshunter 包/CLI 保留兼容，不修改许可。
- PowerShell 直接传多行 apply_patch 的末行校验曾失败，后改用 UTF-8 stdin 调用同一补丁工具成功；未做平台请求。
- 备份位于 .codex-backups/autojobhunter-readme-20261010 和 .codex-backups/automation-monitor-20261010（monitor-interval、safe-draft-retry、legacy-tests、finite-settings、acceptance-finalization 等精确文件备份）。不生成父目录全仓库备份，不删除历史文件。

### 后续真实放行步骤

1. 正常重启当前 8686 后端，确认载入最新磁盘代码、工作目录正确、无其他运行任务。不能绕过执行策略或另起端口来冒充。
2. 从首页 auto_full 开始，各平台先一个未处理且真实评分达标岗位；核账号、任务范围、低频队列、平台原文送达、库/API/日志/卡片资料，再逐步扩大至各2～3个独立样本。保留60～180秒发送等待、deepseek-flash及平台默认/授权话术。
3. 只读检查合适的真实新 HR 回复。没有触发就等待正常轮询；已有拒绝/停用/接管会话不用于凑测试。不恢复旧 full，不发送全部历史积压。
4. 新消息实际触发后核资料来源、上下文/账号隔离、随机等待、快照取消、幂等、安全送达；真实核单卡停用跳过与敏感话题暂停。邮件排队不等于收件箱送达，通知闭环另核。
5. 处理合成/原生消息双表示时先建立可靠关联证据及回归，不按文字删记录、不影响幂等。不将“已修代码”标成“真实全量通过”。

只使用主会话，按用户要求未启动子代理，因此独立审查 unavailable；不出 merge-ready/共识审批结论。未安装 OMX CLI，本记录作为 QA 场景/失败追踪，不伪造其状态。
