# 在本机运行 PPT 审核试验

这套试验把 **Agent Autoloop v1.9.0 的后台调度**接到项目自己的 **PPT API 审核能力**。审核使用后端已经配置的模型服务；不需要额外安装或登录 Codex、Claude，也不需要独立显卡来运行中台。

试验处理的是结构化的教案和 PPT 大纲：核对主题、年龄、教学流程、内容与配图描述之间的对应关系，并在设定的次数内尝试修订。它没有读取实际 PPT 渲染图，不能据此判定图片是否被裁剪、图片人物是否变形、文字是否溢出或版式是否好看。

已有 [工作区试验记录与逐页对照](ppt-review-evaluation.md)。其中明确区分程序回归、Autoloop 调度烟测和构造样本的独立 Agent 语义演示；它不是 Windows 本机真实模型的验收记录。

## 0. 从大纲页面直接使用

更新前端和后端后，新生成的幼教大纲会保存真实教案与本次参考材料，在大纲页显示“内容检查”。日常交互审核可直接使用这个入口，不需要先启动 Autoloop。

1. 等大纲生成、保存完成，点击“检查内容”，或点击“检查并修订”（页面入口最多修订一轮）。
2. 等待区显示实际已用时间，可取消本次等待。取消、刷新或短暂断线后，页面只读取最近任务与结果，不会自动重新提交模型调用。
3. 查看问题原文和建议，点击“查看第 N 页”定位原稿；有修订时可展开逐页对照。
4. 确认修改合适后点击“采用修订稿”，此时才把已复审的版本写入大纲。随后继续确认生成课件。

如果采用请求断线或超时，页面会暂停编辑和生成，先核对服务器是否已保存，再同步真实大纲。点击“重新确认采用结果”只读取状态，不会重复提交采用或模型请求。同步完成前保留旧内容供查看，避免旧稿覆盖服务器的新稿。状态读取等待上限为 20 秒，采用请求等待上限为 30 秒。

页面还提供“保存草稿”及未保存提示。手动编辑、刷新、并发窗口保存导致源版本变化时，旧报告会过期；不能覆盖新的手改内容。当前只支持对有完整快照且仍与快照一致的大纲进行审核：旧课件、手改后已经不同的大纲会明确说明原因，正常保存和生成仍可使用。已经进入幻灯片生成阶段的项目可以查看文稿审核，暂不把修订回写大纲，避免与已生成页面不一致。

查看完整资料、发起审核和采用均检查课件所有者。同一请求重复发送会复用结果，同一课件已有任务时会提示等待。原始教案和参考材料只用于这份课件的审核，不通过普通列表返回。新增入口为：

- `GET /api/v1/ppt/kindergarten/presentation/{id}/review-source`
- `POST /api/v1/ppt/kindergarten/presentation/{id}/review`
- `POST /api/v1/ppt/kindergarten/presentation/{id}/review/apply`

更详细的验证范围见 [流畅度与使用检查记录](ppt-review-usability-check.md)。以下命令行与 Autoloop 用于本机试验和后台调度。

## 1. 运行前准备

需要 Windows PowerShell 5.1 或更新、Node.js 24 或更新、Git。标准库任务脚本支持 Python 3.10 或更新；项目后端仍沿用 `engine/api/pyproject.toml` 要求的 Python 3.11。先启动包含审核接口的本项目后端，并确认其模型配置可用。默认 API 根地址是 `http://127.0.0.1:8000`；如果你的开发服务使用其他端口，显式传入 `-ApiBase`。

新增接口是 `POST /api/v1/ppt/kindergarten/lesson-plan/review`。它只在显式调用时运行，不加入原有默认生成流程，也不写回已保存的 PPT。更新代码后需要重启本机后端，使新接口生效。

审核默认复用现有 planner/DMX 的 OpenAI-compatible 配置及模型。当前适配器只实现这个接口协议；使用原生其他厂商客户端时，应在后端进程配置专用的 `KINDERGARTEN_REVIEW_API_KEY`、`KINDERGARTEN_REVIEW_BASE_URL`、`KINDERGARTEN_REVIEW_MODEL` 三项。不要在客户端脚本中传模型密钥。可选 `KINDERGARTEN_REVIEW_MAX_TOKENS` 为正整数（默认 8192，最大 32768），`KINDERGARTEN_REVIEW_CALL_TIMEOUT_SECONDS` 默认 90 秒（最大 300 秒）。仅设置 `KINDERGARTEN_REVIEW_MODEL` 可以在已有兼容服务中指定审稿模型。

PowerShell 启动脚本：`scripts/start-ppt-review-autoloop.ps1`。

Python 任务入口：`scripts/ppt-review-pilot.py`。

启动脚本仅在项目目录内创建运行时和数据：

| 位置 | 内容 |
| --- | --- |
| `.runtime/ppt-review-autoloop/runtime/` | 自动获取的固定版本中台源码；指定 `-AutoloopPath` 时复用指定目录 |
| `.runtime/ppt-review-autoloop/state/` | 本次试验的规则、状态、任务日志及中台自身的本机访问配置 |
| `.data/ppt-review-autoloop/` | 默认报告基目录；每次任务创建独立子目录 |

项目现有 `.gitignore` 已忽略 `.runtime/` 和 `.data/`。把包含真实课程资料的输入 JSON 放在 `.data/` 中即可。不要把状态目录或认证信息加入 Git。

脚本不会安装系统服务、修改全局 PATH、修改 `CODEX_HOME`，也不会修改 PowerShell 执行策略。`Up` 在前台运行，需要保留终端。

## 2. 准备审核输入

输入文件需要 `brief` 和 `plan`。`plan` 是项目现有的 `KindergartenLessonPlan` 对象，包含 `meta`、`lesson_goals`、`lesson_arc`、`slides`；可以使用现有生成接口返回的完整教案对象。不要把接口外层响应或 PPT 文件路径当成 `plan`。

`brief` 表达原始教学要求，不要用生成稿反推要求，否则审核容易把偏题内容当作正确目标。

| 字段 | 说明 |
| --- | --- |
| `brief.topic` | 课程主题，如“比较章鱼与海豚的身体和运动方式” |
| `brief.age_group` | 年龄段，如 `4-5岁` |
| `brief.domain` | 使用已有领域枚举，如 `science` |
| `brief.content_mode` | 使用服务支持的模式，例如 `classroom` |
| `brief.duration_minutes` | 预期时长 |
| `brief.n_slides` | 预期页数 |
| `brief.instructions` | 聚焦范围、课堂要求、不能遗漏的活动 |
| `brief.source_context` | 本次允许依据的参考材料；没有则留空 |
| `plan` | 完整的现有教案对象 |
| `max_revision_rounds` | `0` 到 `2`，默认 `0`；先只审，再比较是否需要自动修订 |
| `timeout_seconds` | 本次审核请求的时间预算，默认 `120` |
| `max_model_calls` | 本次任务的调用尝试上限，最多 `5`；含未提交的失败尝试，不等同于已计费次数 |

下面展示如何把一份已保存的完整教案包装成请求；`source-plan.json` 必须是真实的教案对象，不能使用省略号代替字段：

```powershell
$plan = Get-Content .\.data\source-plan.json -Raw -Encoding UTF8 | ConvertFrom-Json
$request = @{
    brief = @{
        topic = '比较章鱼与海豚的身体和运动方式'
        age_group = '4-5岁'
        domain = 'science'
        content_mode = 'classroom'
        duration_minutes = 20
        n_slides = $plan.slides.Count
        instructions = '围绕章鱼与海豚的可观察差异展开，安排观察、比较和分类活动。'
        source_context = ''
    }
    plan = $plan
    max_revision_rounds = 0
    timeout_seconds = 120
    max_model_calls = 5
}
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
    (Join-Path $PWD '.data\review-request.json'),
    (ConvertTo-Json -InputObject $request -Depth 50),
    $utf8
)
```

示例要求应替换成老师最初的需求。若使用随试验提供的故障样例，它是人为构造的测试输入，用来验证能否指出已知问题，不能代表平台正常生成稿的质量。

## 3. 先直接调用一次审核 API

在项目目录执行：

```powershell
python .\scripts\ppt-review-pilot.py `
  --input .\.data\review-request.json `
  --check-only
```

预检只核对基本输入和所需 API 路由，不调用模型、不创建报告目录。它优先读取 `/openapi.json`；文档没有开放时，使用无付费的 GET 探测实际 POST 路由。预检通过不代表模型配置或模型响应已经验证。旧后端、未启动、认证失败都会给出明确提示。

确认服务可达后运行：

```powershell
python .\scripts\ppt-review-pilot.py `
  --input .\.data\review-request.json `
  --output .\.data\ppt-review-autoloop `
  --api-base http://127.0.0.1:8000
```

这一步直接验证“读取教案 → API 审核 → 保存报告”，便于区分 API/模型问题与调度问题。它会调用后端配置的模型并消耗对应额度。

正常运行也会先预检。发送前会显示阶段，等待期间每 15 秒显示实际等待时长；没有虚构的完成百分比。普通命令行和 Autoloop 共用输出基目录里的在途记录，避免同一目录重复启动。

脚本也支持先按 `--topic`、`--instructions`、`--slides` 调用现有教案生成接口，再审核新稿。具体可选参数以 `python .\scripts\ppt-review-pilot.py --help` 为准；用于效果比较时，优先使用这一模式或平台刚生成的真实稿件。

用一份新稿检验完整文本流程：

```powershell
python .\scripts\ppt-review-pilot.py `
  --topic '海洋动物的外形有什么不同' `
  --age-group '4-5岁' --domain science --slides 8 `
  --instructions '核心目标是通过观察比较海豚、海龟和章鱼的外形。用指认和口头表达组织观察、比较、回顾；活动围绕这一个目标展开。' `
  --max-revisions 2 --timeout 360 `
  --output .\.data\ppt-review-live
```

新稿生成与审核都会使用后端模型。审核报告里的调用记录只统计独立审核和修订阶段，原生成接口内部的解析重试与消耗没有纳入这份计量，不应把该数字当作生成加审核的总费用。输出的 `generation-response.json` 保留生成端返回的实际信息。

已有人工构造样例可直接作为 `--input` 使用：`scripts/fixtures/ppt-review-ocean.json`。它的程序结构检查会通过，但故意包含第 3 页配图描述不符、第 5 页主题偏移、第 6 页活动要求不适龄；这些是用于验证语义审核的预设问题，不能写成实测召回率或正常生成的错误率。

如果服务需要认证，在启动任务的终端设置 `PPT_REVIEW_BEARER_TOKEN`。通过已有的本机密钥管理方式注入该环境变量，不要把 Token 写进输入文件、脚本或 `rules.json`。后面的中台任务从 **Up 所在终端**继承这个变量，仅在 Run 终端设置不能传给已经启动的 worker。

## 4. 准备中台并运行一单

以下命令从项目根目录执行。若目录中尚无中台源码，`Setup` 自动获取官方仓库的固定标签 `v1.9.0`；已有离线源码时可以用 `-AutoloopPath 'D:\tools\agent-autoloop'` 指定。脚本只接受该标签对应的干净检出，不会切换或覆盖你已有的其他分支。

### 终端一：配置并保持运行

```powershell
.\scripts\start-ppt-review-autoloop.ps1 `
  -Mode Setup `
  -InputPath .\.data\review-request.json

.\scripts\start-ppt-review-autoloop.ps1 `
  -Mode Up
```

`Setup` 在下载中台前先检查输入和 API，因此先启动更新后的本机后端。它会找到项目虚拟环境或 PATH 中的 Python；需要指定时加 `-PythonPath 'D:\Python311\python.exe'`。默认选用一个空闲的本机端口，也可以通过 `-Port 3350` 固定。首次配置后的路径和端口会记录下来，后续 `Up`、`Run`、`Status` 自动复用，`InputPath` 也可以省略。

使用自定义路径和 API 的完整配置例子：

```powershell
.\scripts\start-ppt-review-autoloop.ps1 `
  -Mode Setup `
  -ProjectPath 'D:\projects\xfyun-ai-ppt-mvp' `
  -AutoloopPath 'D:\tools\agent-autoloop' `
  -InputPath '.data\review-request.json' `
  -OutputPath '.data\ppt-review-results' `
  -ApiBase 'http://127.0.0.1:8000' `
  -Port 3350
```

相对输入、输出和运行时路径均相对于 `ProjectPath`。指定非本机 API 地址时，确认它就是本次授权试验的服务；脚本不会自行寻找线上服务。

### 终端二：提交并看结果

```powershell
.\scripts\start-ppt-review-autoloop.ps1 `
  -Mode Run

.\scripts\start-ppt-review-autoloop.ps1 `
  -Mode Status
```

一条规则、单个 Agent 和 worker 的并发均为 `1`。还有排队、执行或结果不确定的轮次时，`Run` 拒绝再次提交。默认没有定时触发，也不连接飞书、邮件或其他对外通知；结果通知保存在中台状态中。

`Run` 用跨进程独占文件句柄保护状态检查和提交，防止两个终端同时排入任务。`submit.lock` 空文件只是互斥载体，关闭句柄就已释放，不需要手动删除。

在运行期间不要改动当前输入 JSON。要换输入路径、输出目录或 API，先等当前任务结束，在 `Up` 终端按 `Ctrl+C`，再用新参数执行 `Setup` 和 `Up`。内容修改后再次审核也应作为一单新的试验，保留原来的报告用于比较。

## 5. 怎样判断实际效果

每次任务在输出基目录下新建 `YYYYMMDD-HHMMSS-<8位随机标识>` 子目录，终端和中台通知会给出实际路径。

| 文件 | 用途 |
| --- | --- |
| `original-plan.json` | 本次实际送审的原稿 |
| `review.json` | 审核结论、问题、修订过程与失败信息；以实际返回字段为准 |
| `comparison.html` | 在浏览器中对照原稿、问题与修订内容 |
| `reviewed-plan.json` | 当前已完成语义审核的采用稿，可能仍是原稿；是否通过必须读取 `review.json.status` |

建议先固定同一组真实主题、同一模型配置，比较以下结果：

1. 审核指出的问题是否能定位到原稿中的具体页面或字段。
2. 是否识别了偏离老师原始要求的内容，而非只提出语言润色。
3. 修订是否消除了原问题，同时保留课堂操作、必要信息和正确内容。
4. 老师需要手工改动的时间是否减少。
5. 一单增加了多少模型调用、耗时和实际费用。

人工构造的故障样例用于检查流程和已知问题；判断“值得正式接入”还需要用本机真实新稿做上述比较。中台启动、规则检查、HTTP 成功、模型返回、教学审核通过，是不同的验收结果。当前脚本和文档本身不证明你的 Windows 机器、模型或课程已跑通。

## 6. 失败、超时与停止

普通 CLI 模式失败时返回非零退出码。`--autoloop` 模式会保存失败/超时等结果，并用明确的失败通知结束本轮，正常交回这类报告时进程退出码为 `0`，以免中台把业务失败自动重复提交给付费模型。因此 **中台显示 done 只表示这一轮已结束，不代表审核通过**。

普通 CLI 与 Autoloop 模式都会在输出基目录建立原子在途锁。若进程异常退出、请求超时或远端是否执行完成尚不明确，后续运行应停下来要求核对，不能盲目重发。按报告提示核实后端任务已结束、没有同一审核仍在执行，再手动处理残留锁；不要把删除锁作为固定重试步骤。

等待时按 `Ctrl+C` 会保存明确的 `cancelled` 报告，说明本地等待已结束、远端是否完成仍未知；在途记录会保留。普通 CLI 返回退出码 `130`。这不能证明供应商已停止执行或计费。

需要停止具体轮次时，在终端二先用 `Status` 取得轮次编号，再使用原生命令：

```powershell
$env:AGENT_AUTOLOOP_HOME = Join-Path $PWD '.runtime\ppt-review-autoloop\state'
$entry = Join-Path $PWD '.runtime\ppt-review-autoloop\runtime\bin\agent-autoloop.ts'
# 使用 -AutoloopPath 配置了其他源码目录时，将 $entry 改成那个目录下的入口。
node $entry stop 轮次编号
```

停止客户端不能证明远端模型调用立即取消。查看报告和后端日志，确认后再开始下一单。结束使用前先处理仍在运行的轮次，再在 `Up` 终端按 `Ctrl+C`；状态和报告会保留。

`command` 适配器按固定的 Python 参数数组启动任务，事件内容不能指定程序、路径或权限。`access: read` 不会为通用命令额外建立系统沙箱；本试验的范围由固定脚本、指定 API 和输出目录决定。它会创建报告文件，不会自动推送代码、发布站点或把结果覆盖进老师的资源库。

## 上游依据

- [Agent Autoloop v1.9.0](https://github.com/KKKKhazix/agent-autoloop/tree/v1.9.0)
- [官方安装说明](https://github.com/KKKKhazix/agent-autoloop/blob/v1.9.0/INSTALL.md)：Node 24、前台运行和 `--no-service`。
- [命令适配器](https://github.com/KKKKhazix/agent-autoloop/blob/v1.9.0/plugins/command/agent.ts)：固定参数数组及完成回执。
- [安全边界](https://github.com/KKKKhazix/agent-autoloop/blob/v1.9.0/SECURITY.md)：通用命令的权限仍由运行环境决定。
