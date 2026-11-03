# legio

一个软件工厂。你在项目里打一个 `centuria` 标签,`legio` 就会让一组固定角色把这条 issue
走完:守门 → 立旗 → 施工 → 门禁 → 评审 → 裁决 → 你合 PR。

- **legio** 是命令,也是这套系统本身。
- **centuria** 是驻扎在一个项目里的那一套文件(`<项目>/.centuria/`),也是一个单位。
- 一个 centuria 一个项目。多个项目就是多个 centuria,由同一个 `legio` 管。

## 分工:legio 不知道流水线长什么样

这一点决定了整套东西能不能长期演进,所以说在前面。

```
legio                          centuria（每个项目一份）
─────                          ──────────────────────
发现有哪些 centuria             状态机、job.json
调 add / remove / labels        有哪些阶段
调 job next  → 拿工单           每个阶段配哪个角色
按 adapter 起宿主进程           产物叫什么、首行写什么
调 job done  → 让它自己推进      什么算通过
跨项目的看板                   提示词正文（角色 + 本轮上下文）
```

legio 只跟 centuria 打交道。**它连 agent 都不起**——起进程是 centuria 的 `bin/run` 干的,
legio 只是把 host spec 的路径传进去。

**legio 唯一的决策是:哪个项目、哪些 issue 要做。**
它调 `job queue --json` 拿队列,对 `kind: new` 的行调 `job create <issue>`,
然后就撒手。之后派谁、怎么跑、什么时候停,全是 centuria 的事。

```bash
legio sync webapp     # 把打了 centuria 标签的新 issue 变成 job
legio run  webapp     # 派活 + 让 centuria 自己并发跑
```

核心就两个命令:

```
job next <id> --json   工单：{kind: agent|gate|human|done|noop,
                             role, tier, cwd, role_file, header, task}
job done <id>          centuria 自己读产物、自己决定推进到哪，返回新状态
```

所以:

- **legio 里没有阶段名、没有角色名、没有 `STATUS: READY` 这种字符串。**
  (可以自己验:`grep -nE "tesserarius|build\.md|VERDICT:" legio` 是空的)
- 升级流水线 = 重拷 `.centuria/`,`legio` 一行不用改。
- 加一个阶段、换一个角色名、改一版产物格式,都只动 centuria。
- 反过来,想接一个新宿主(第四个、第五个 agent CLI),只动 `hosts/*.json`,centuria 一行不用改。
- **legio 可以整个删掉。** centuria 自带 `bin/run`,自己就能跑完一条 job。

**边界一句话:centuria 管项目,legio 管把活交给某个宿主。**

## 八个角色

名字是罗马军团的职务。**光看名字猜不出功能,所以每个角色文件的第一节都写了功能。**
这里先列一张表:

| 罗马名 | 相当于 | 功能(一句话) | 产出 | 出场条件 |
|---|---|---|---|---|
| **Tesserarius** | intake | **守门**:这个 issue 值不值得建、建多大、风险多高 | `intake.md` | 每个 issue 一次 |
| **Signifer** | spec-writer | **立旗**:把需求写成可执行、可验收的 spec | `spec.md` | ACCEPT 之后 |
| **Fabri** | builder | **施工**:写代码、跑检查、提交、推分支、开 PR | `build.md` + 代码 | 每轮一次 |
| **Probator** | reviewer-code | **验工**:做得对不对、范围对不对、测试有没有 | `review-probator.md` | 每轮 |
| **Medicus** | reviewer-security | **验伤**:注入、越权、泄密、依赖风险 | `review-medicus.md` | 仅 `security` 面 |
| **Mensor** | reviewer-ux | **量人**:用户能不能看懂、走通、出错时有救 | `review-mensor.md` | 仅 `ui` 面 |
| **Librator** | reviewer-ui | **定平**:对齐、间距、层级、主题一致性 | `review-librator.md` | 仅 `ui` 面 |
| **Primus Pilus** | approver | **裁决**:能不能直接合,还是要人拍板 | `decision.md` | 全部评审 PASS 之后 |

八个角色合起来是一个 **contubernium**(八人帐队);它们所属的单位是 **centuria**。
角色是固定的 8 个,**实例不是**:一个卡到满轮的 job 会 spawn 18 次以上。

## 装到一个项目里

```bash
legio add ~/dev/webapp --host claude-code
```

这会:

1. 把 `legio/centuria/` 拷成 `~/dev/webapp/.centuria/`,
   并把 `default_host_spec` 指到 `legio/hosts/<宿主名>.json`
2. 把 `.centuria/`、`.worktrees/`,**以及该宿主自己会往项目里写的路径**
   (比如 claude 的 `.claude/settings.local.json`)写进 `~/dev/webapp/.git/info/exclude`

**注意第 2 点:写的是 `.git/info/exclude`,不是 `.gitignore`。**
所以这些文件**永远不会进入 git 历史**,也不会改项目里任何被 git 跟踪的文件。
`git status` 依旧是干净的。

宿主自己造的东西不归 legio 管,由 profile 里的 `host_paths` 声明、由 `legio add` 顺手排除。

然后做两件事:

```bash
# 1. 填项目自己的检查
$EDITOR ~/dev/webapp/.centuria/checks.sh

# 2. 核对配置
$EDITOR ~/dev/webapp/.centuria/config.json   # base_branch / protected_paths / merge_policy

# 3. 建 GitHub 标签（打上 `centuria` 的 issue 才会被处理）
legio labels webapp

# 4. 体检
legio doctor webapp
```

`.centuria/` 是隐藏目录,项目根看过去是干净的。

## 跑起来

```bash
legio ls                      # 有哪些 centuria
legio inbox                   # 现在有什么在等你
legio next webapp             # 下一步做什么,以及要交给 agent 的完整提示词
```

`legio next` 会把**角色文件 + job 头 + 本轮上下文**拼成一段可以直接贴给 agent 的提示词。
agent 干完活之后:

```bash
legio advance webapp:001-add-subtract spec      # 或者 build / gate / review / approve ...
legio route webapp:001-add-subtract             # 按风险挑评审
legio gate webapp:001-add-subtract              # 跑 checks.sh
```

流水线:

```
issue 打了 `centuria` 标签
   │
   ▼
Tesserarius ──NEEDS-INFO──► 去 issue 里反问作者,停在这
   │        └─REJECT─────► 说明理由,摘标签
   ▼ ACCEPT(可能缩范围)+ 打 risk / surfaces
route (脚本)                → 评审集合 + 模型档位
   ▼
Signifer                    → spec.md
   ▼
Fabri                       → 提交 · 推分支 · draft PR "Closes #n"
   ▼            ▲
gate (脚本) ──FAIL──┘        checks.sh + protected_paths
   ▼ PASS
评审(并行)──CHANGES──► Fabri(最多 max_rounds 轮)
   ▼ 全 PASS
Primus Pilus ──APPROVE──► PR 转 ready,等你合
              └─ESCALATE─► PR 转 ready,带具体问题等你判
   ▼
你在 GitHub 上合 PR  ← 默认 merge_policy = human,legio 永远不替你合
   ▼
merged(legio sync 会自动发现并收尾)
```

## 谁来驱动

**centuria 自己就能跑完一条 job,legio 只负责发现、装机、看板。**

```bash
# 方式一：legio 转发（推荐日常用,它顺手帮你选 host spec）
legio run webapp --agent claude-code --max-steps 20

# 方式二：只让 legio 出提示词,你自己贴给 agent
legio next webapp

# 方式三：绕开 legio，centuria 自己跑（用 add 时记下的 default_host_spec）
cd ~/dev/webapp
.centuria/bin/centuria run

# 想跑几路兵，也是 centuria 自己决定
.centuria/bin/centuria run --all          # 最多 concurrency 个 job 并发
```

三种方式走的是**同一个循环**:`job next` 拿工单 → 起一个 host → `job done` 结算。

## centuria 自己的命令

```bash
cd ~/dev/webapp

.centuria/bin/centuria run [<job>]                       # 跑到底
.centuria/bin/centuria run --all                         # 最多 concurrency 个并发
.centuria/bin/centuria next <job>                       # 下一步(工单 JSON)
.centuria/bin/centuria done <job>                       # 结算并推进
.centuria/bin/centuria gate <job>                       # 跑 checks.sh
.centuria/bin/centuria summary                          # 一张表
.centuria/bin/centuria view                             # JSON
.centuria/bin/centuria queue                            # 队列
.centuria/bin/centuria create <issue>                   # 收活
.centuria/bin/centuria route <job>                      # 重新路由
.centuria/bin/centuria advance <job> <stage>            # 手动推
```

`--host-spec` 可以不给:`.centuria/config.json` 的 `default_host_spec` 就是
`legio add --host <宿主>` 时记下的路径。centuria 自己不拥有 host 注册表——
注册表只有一份,住在 `legio/hosts/`,项目里只记"我惯用哪一件"。

`concurrency` 不是摆设:`centuria run --all` 会真的同时开那么多路,每路一个进程、
一个 worktree、一条分支。

## 命令

```
legio add <path>                     驻扎一个 centuria
legio remove <path>                  撤走(会删掉 job 状态)
legio ls                             所有 centuria 概览
legio status [--all]                 所有 job
legio inbox                          等你决策的事,最急的在前
legio next <project>[:<job>]         下一步 + 给 agent 的提示词
legio route <project>:<job>          按风险/面挑评审
legio gate <project>:<job>           跑门禁
legio advance <project>:<job> <阶段>  推进状态机(非法迁移会被拒)
legio say <project>:<job> <文字>      反馈,打回给 Fabri 再来一轮
legio reject <project>:<job> <理由>   打回并关闭
legio run <project>[:<job>] [--agent <host>]   派活,再让 centuria 自己跑
legio hosts [--json]                  列出可用的宿主 adapter(--json 输出 JSON)
legio labels <project>                创建三个 GitHub 标签
legio sync [<project>]               派活:把新 issue 变成 job,再看队列
legio doctor [<project>]             体检
```

## 布局

```
legio/                          ← 系统母版
├── legio                       ← 命令
├── config.json                 ← projects_root、stale 阈值
└── centuria/                   ← 拷进项目的模板
    ├── bin/centuria            ← 统一入口,转发到下面三个
    ├── bin/job                 ← 状态机,唯一写 job.json 的(不起进程)
    ├── bin/run                 ← 循环 + host adapter 解释器(起 agent)
    ├── bin/gate                ← 门禁,跑 checks.sh
    ├── roles/*.md              ← 八个角色定义
    ├── config.json             ← 项目级:路由、受保护路径、合并策略
    ├── checks.sh               ← 项目自己的检查(要你填)
    └── version.json            ← 由 legio add 写入的版本戳
```

装好之后,项目里长这样:

```
<项目>/
├── .centuria/
│   ├── bin/ roles/ config.json checks.sh version.json
│   └── jobs/<job>/           ← issue.md intake.md spec.md build.md round-N/ decision.md …
├── .worktrees/<job>/         ← 每个 job 一个独立 worktree
└── (项目自己的代码,一个 factory 文件都没有)
```

## 加角色 / 加评审维度

几乎免费,因为路由是查表的:

1. `config.json` 里 `surface_reviewers` 加一项(比如 `"perf": {"ballistarius": "medium"}`)
2. `roles/` 加一个角色文件,首行格式照抄别的
3. Tesserarius 的提示词里教它输出这个新 surface

状态机、gate、route 一行都不用改。如果 intake 吐出一个 config 里没有的 surface,
`route` 会**直接报错退出**,不会静默漏掉。

加**流水线阶段**才要改代码:`bin/job` 顶部的 `TRANSITIONS` 和 `advance()` 里的分支。

## 两条硬规矩

1. **`job.json` 只有一个写入者**:`bin/job`。它带文件锁、原子替换、状态机校验。
   任何工具想改状态,都必须走它。
2. **legio 不替你合 PR**。默认 `merge_policy: "human"`,Primus Pilus 判 APPROVE
   也只是把 PR 转成 ready 并告诉你;真正的合并是你在 GitHub 上点的。
   想自动化,把 `merge_policy` 改成 `"legio"`。

## 三个词,别再混

这套东西里 **role / roster / host** 是三件不同的事,名字像但位置完全不同:

| 词 | 是什么 | 住在哪 | 数量 |
|---|---|---|---|
| **role** | 一个工种的说明书(职责、产出、输出格式) | `<项目>/.centuria/roles/*.md` | 固定 8 个 |
| **roster** | 这个 job 派哪几个 role 出场、各用什么档位 | `job.json` 的 `roster` 字段 | 每个 job 一份 |
| **host** | 怎么把一张工单交给某个 agent CLI(命令、flag、怎么递 prompt) | `legio/hosts/*.json` | 有几种 CLI 就有几份 |

所以:centuria 手里是 **roles**;它给每个 job 排一张 **roster**;legio 拿 **host** 去执行。

## 谁能记得住

| 层 | 数量 | 生命周期 | 有记忆吗 |
|---|---|---|---|
| legio | 1 | 常驻 | 无。它只是驱动 |
| **centuria** | 每个项目 1 份 | 跟项目同寿 | **有**。`jobs/` 里所有 job.json 和产物 |
| job | 每个 centuria 管 N 个 | 到 merged / rejected | 有。自己的 job.json + `round-N/` |
| **agent 实例** | 每个 job 多个 | 一次调用,写一个文件就退出 | **无**。全靠工单 |

**真正把 agent 拉起来的是 centuria**(`bin/run`),不是 legio——所以在没有 legio 的机器上,
centuria 照样能自己跑完一条 job。

agent 是 centuria 派出去的代表,不是有状态的小助手:**工单进,一个文件出,退出**。
所以会话崩了能续跑、换宿主不影响结果、agent 挂了也不会脏状态——
记忆只在 centuria 的文件里。

## 宿主适配器

循环和提示词拼装都在 centuria 的 `bin/run` 里。它把 `job next` 给的**工单**交给一个宿主 CLI:
工单里已经有角色文件路径、本轮任务正文、工作目录和模型档位。
宿主干完活、写出产物文件,`bin/run` 再调 `job done`,由 `bin/job` 判断成没成
(**看产物,不看模型说了什么**)。

```
legio/hosts/
├── claude-code.json   角色文件 → --append-system-prompt-file(真 system prompt)
├── codex.json         角色文件拼进 prompt(codex 没有单独的系统提示词 flag)
├── dsh.json           dsh headless
├── gemini.json        未测试,本机没装
├── echo.json          干跑:只打印提示词
└── fake.json          测试用:假 agent,替你把产物写出来
```

```bash
legio run webapp --agent claude-code --max-steps 20
legio run webapp --dry-run                # 看它打算怎么调
legio run webapp --agent claude-code --yolo   # 追加"别问我,直接干"的启动参数
```

一份 profile 只有十几个字段,四个宿主共用同一个 runner:

| 字段 | 作用 |
|---|---|
| `command` | 二进制 + 固定参数 |
| `yolo` | `--yolo` 时才追加的自主执行开关 |
| `role.mode` | `system`(单独传系统提示词)或 `concat`(拼进 prompt) |
| `prompt.via` | `stdin` 或 `arg` |
| `cwd.mode` | `process`(进程 cwd)或 `flag`(如 codex 的 `-C`) |
| `model.flag` | 怎么指定模型 |
| `model_tiers` | **档位 → 具体模型名**(宿主相关) |
| `host_paths` | 这个宿主会在项目里造的路径,`legio add` 时排除 |
| `timeout_seconds` | 单次调用的超时 |

**`--yolo` 默认关。** 非交互跑 agent 必须预授权工具,否则它会卡在"要不要执行这条命令"上;
但那些开关等于关掉所有确认,所以你得显式开。

## 模型档位

`centuria/config.json` 里角色绑定的是**档位**(`light` / `medium` / `strong`),不是模型名——
所以 centuria 的配置是宿主无关的。档位到具体模型的映射在**宿主的 profile** 里:

- Claude 是 `haiku / sonnet / opus`
- Codex 是另一套
- 换宿主只换 profile,centuria 一行不动

非评审角色的档位在 `role_tiers` 里(Tesserarius / Signifer / Fabri / Primus Pilus 都是 `strong`),
评审角色按风险路由。

默认路由:

| 风险 | 评审 | 档位 |
|---|---|---|
| low | Probator | light |
| medium | Probator | medium |
| high | Probator | strong |
| + `ui` 面 | Mensor / Librator | medium / light |
| + `security` 面 | Medicus | strong |

所以一个低风险、不碰界面的改动只跑一个便宜的评审;一个碰了 UI 又碰权限的改动
会跑四个。
