# TypeSafe 回复判断预览（实验阶段）

此阶段提供桌面界面和命令行两种手动预览，不接入 QQ/微信读取、DeepSeek 生成或消息发送。
桌面预览会在使用者明确勾选本次上传同意后联网；自动回复流程不会调用 TypeSafe。

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

接入真实发送流程前，还需用经过授权的代表性样例评估误判率、实际费用与延迟，
特别测试上下文不足、否定表达、讽刺、告别、风险与多条消息混合等情况。
还需设计配置界面、加密密钥存储、停止/联系人变化时的过期结果失效处理，
并同步隐私说明及重新打包验收。本阶段不更改既有自动回复安全逻辑。

## 协议依据

2026-09-22 核对官方 HTTP API、Choice 和意图分流文档：

- https://docs.typesafe.ai/api.md
- https://docs.typesafe.ai/primitives/choice.md
- https://docs.typesafe.ai/patterns/intent-routing.md

使用 POST /v1/systemone、jev-latest、Choice 的 answers.route 返回结构。
模型别名可能变化，真实上线前应再次核实并评估。
