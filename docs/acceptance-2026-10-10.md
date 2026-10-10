# AutoJobHunter 低频自动化验收记录（2026-10-10，上海时区）

本文是持续更新的证据记录，不是“全部通过”声明。只使用主会话；修改前备份，不触碰凭据、用户简历和浏览器登录资料。手动流程必须保留。

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
| AUTO-03 | 达标投递、页面确认、本地会话补齐 | 五层真实证据 | 没有人工确认环节；确实送达且不串会话 | 第二轮地址失败已修；第三轮两平台 succeeded/reconciled 各 2；BOSS 真实列表和目标聊天显示本轮“您好”，智联真实页面证据仍待补，不宣称五层全部通过 | 不重复投递本轮岗位 |
| AUTO-04 | 持续轮询、HR 回复、资料生成回复 | 真实监控 + 测试 | 只处理本轮已验证会话、敏感问题人工接管 | 尚未真实验收；154 个相关 Python 测试通过仅是离线证据 | 不伪造 HR 回复 |
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
