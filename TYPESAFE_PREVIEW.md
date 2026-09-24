# TypeSafe 在线预分流与手动预览（实验阶段）

v0.1.3-preview 除原有手动预览外，新增可选的 TypeSafe 在线自动分流。
自动分流默认关闭；公开版下游仍固定为 DeepSeek，不包含私有本地回复模型。

## 自动分流

1. 在桌面界面的 TypeSafe 区域输入独立的 TypeSafe API Key。
2. 阅读并勾选“启用在线自动分流”，确认每批聊天文字及最近最多 4 条历史会发送给 TypeSafe，可能增加费用。
3. 点击“保存 TypeSafe 设置”。关闭时取消勾选后再次保存。

启用后流程为：现有本地风险规则 → TypeSafe 一次请求分别判断“回复／无需回复／本人处理”和回复方向 → 仅“回复”才调用 DeepSeek 生成 → 发送前重新核对联系人和新增消息。“无需回复”跳过本轮；“本人处理”、低置信度或接口失败会暂停自动回复，须由本人检查后重新启动。
TypeSafe 只返回预定义选项和置信度，不生成聊天回复、不直接调用 DeepSeek，也不拥有发送权限。输入超过 6000 字不会上传。最多最近 4 条历史各保留最后 1200 字；待分析内容不包含联系人备注名、关系背景、截图、日志或 DeepSeek 密钥，TypeSafe 密钥仅用于请求头认证。

实验门槛为回复动作置信度 0.85 且所选概率 0.90；回复方向也须达到相同门槛。门槛尚需按真实场景评估，**不代表正确率或安全保证**。已有的手动预览依旧要求每次勾选上传同意，与自动分流开关互不代替。

## 运行

在本项目已安装 requirements.txt 的 Python 3.12 环境中运行：

```powershell
python typesafe_preview.py
```

输入虚构或脱敏样例。默认只执行现有本地风险检查，其余情况返回 disabled；
不会用规则冒充 TypeSafe 的实际判断。

开发测试（模拟服务返回、禁止真实网络）：

```powershell
python -m unittest test_typesafe_preview -v
```

## 以后进行真实服务测试

命令行真实测试需要先取得独立的 TypeSafe API Key，
通过进程环境变量 TYPESAFE_API_KEY 提供；不要把密钥写进源码、命令参数或截图。
工具不保存密钥，不读取现有 DeepSeek Key。只有同时提供下面两个开关才允许请求：

```powershell
python typesafe_preview.py --online --consent
```

上述操作会把本次手动输入的完整文字发送到 TypeSafe，可能产生费用。
不自动获取联系人、历史、关系设置、截图或日志；正文里自行填写的个人信息仍会被发送，
工具不承诺自动脱敏。没有本次上传同意、密钥或有效输入时不会请求外部服务。

## 判断与安全边界

- 先复用 core.detect_risk；命中或检查异常时直接建议转人工，不发送外部请求。
- reply：建议回复；no_reply：建议不回复；human：建议本人处理。
- 所有结果 automatic_send_allowed 都为 false，不生成也不发送聊天回复。
- 格式异常、服务失败、超时或低置信度均转人工，不自动重试、不降级放行。
- HTTP 固定为 TypeSafe 官方端点，禁止重定向，连接/读取超时为 3.05/8 秒。
- 0.85 置信度与 0.90 所选概率是待评估的实验门槛，不是正确率或安全保证。
- 最长 2000 字；过长输入拒绝，不截掉末尾后继续判断。
- 模拟测试只验证程序行为，不验证模型对中文、隐含风险或提示注入的实际识别能力。

自动分流已接入在线公开版，但发布默认关闭。正式扩大使用前，仍需用经授权且脱敏的代表性样例评估误判率、费用与延迟；尤其关注上下文不足、否定表达、讽刺、告别、风险与多条消息混合等情况。单元测试只证明程序按模拟结果执行，不能证明 TypeSafe 在实际聊天中的准确率。

## 协议依据

2026-09-24 核对官方 HTTP API、Choice、State、置信度和意图分流文档：

- https://docs.typesafe.ai/api.md
- https://docs.typesafe.ai/primitives/choice.md
- https://docs.typesafe.ai/patterns/intent-routing.md
- https://docs.typesafe.ai/concepts/state.md
- https://docs.typesafe.ai/confidence.md

使用 POST /v1/systemone、jev-latest、两道 Choice 问题和 answers 中对应的 action／direction 结构化结果。
模型别名可能变化，真实上线前应再次核实并评估。
