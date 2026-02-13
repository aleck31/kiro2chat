# Kiro / CodeWhisperer API 逆向工程笔记

## 认证链路

### Kiro CLI 认证方式 (IdC / 企业 SSO)

1. **Token 存储位置**: `~/.local/share/kiro-cli/data.sqlite3`
   - 表: `auth_kv`
   - 有效 key: `kirocli:odic:token` (access/refresh token) + `kirocli:odic:device-registration`
   - 旧版 `codewhisperer:odic:*` 是 Q CLI 遗留，已过期

2. **IdC Endpoint**: `https://oidc.us-east-1.amazonaws.com/token`
   - 用 refresh token 换 access token
   - Aleck 的 IdC 认证是企业 SSO: `d-9067ddc38a.awsapps.com`

3. **Social 认证方式** (另一种):
   - Endpoint: `https://prod.us-east-1.auth.desktop.kiro.dev/refreshToken`
   - kiro2api (Go) 同时支持两种方式

### Token 刷新流程
```
SQLite (refresh_token) → IdC OIDC /token → access_token + profile_arn
```

## CodeWhisperer API

### Endpoint
```
POST https://codewhisperer.us-east-1.amazonaws.com/generateAssistantResponse
```

### Headers
```
Content-Type: application/json
Authorization: Bearer <access_token>
x-amzn-codewhisperer-optout: true
```

### 请求格式

```json
{
  "conversationState": {
    "chatTriggerType": "MANUAL",  // ⚠️ 必须是 MANUAL，不能用 AUTO
    "conversationId": "<uuid>",
    "currentMessage": {
      "userInputMessage": {
        "content": "用户消息",
        "modelId": "CLAUDE_SONNET_4_20250514_V1_0",
        "origin": "AI_EDITOR",
        "userInputMessageContext": {
          "toolResults": [],
          "tools": [
            {
              "toolSpecification": {
                "name": "tool_name",
                "description": "描述 (最大 10000 字符)",
                "inputSchema": {
                  "json": {
                    "type": "object",
                    "properties": { ... },
                    "required": [ ... ]
                  }
                }
              }
            }
          ]
        },
        "images": []
      }
    },
    "history": [
      {
        "userInputMessage": {
          "content": "历史用户消息",
          "modelId": "CLAUDE_SONNET_4_20250514_V1_0",
          "origin": "AI_EDITOR"
        }
      },
      {
        "assistantResponseMessage": {
          "content": "历史助手回复",
          "toolUses": null
        }
      }
    ]
  },
  "profileArn": "arn:aws:codewhisperer:us-east-1:222829864634:profile/NGQVMVC74C7X"
}
```

### 关键字段说明

#### chatTriggerType
- `MANUAL` — 正常聊天（默认，包括带 tools 的请求）
- `AUTO` — 仅在 tool_choice 强制工具调用时使用（如 `type: "any"` 或 `type: "tool"`）
- ⚠️ 普通聊天带 tools 时用 AUTO 会导致 400 "Improperly formed request"

#### modelId（已验证的值）
| 名称 | CodeWhisperer Model ID |
|------|----------------------|
| Claude Sonnet 4.5 | `CLAUDE_SONNET_4_5_20250929_V1_0` |
| Claude Sonnet 4 | `CLAUDE_SONNET_4_20250514_V1_0` |
| Claude 3.7 Sonnet | `CLAUDE_3_7_SONNET_20250219_V1_0` |
| Claude Haiku 4.5 | `auto` |

Opus 系列的 model ID（如 `claude-opus-4.5`, `claude-opus-4.6`）在 JS 客户端代码中出现过，但未在 kiro2chat 中成功验证。可能需要特殊的请求格式或权限。

#### origin
- 固定为 `"AI_EDITOR"`

#### System Message 处理
CodeWhisperer 没有原生的 system role，需要将 system message 注入为 history 中的第一轮对话：
```json
{
  "userInputMessage": { "content": "<system prompt>", ... },
  "assistantResponseMessage": { "content": "OK", "toolUses": null }
}
```

#### Tool Results 回传
当 Claude 返回 tool_call 后，需要把工具执行结果放在下一轮的 `toolResults` 中：
```json
"userInputMessageContext": {
  "toolResults": [
    {
      "toolUseId": "tool_call_id",
      "content": [{ "text": "工具执行结果" }],
      "status": "success"  // 或 "error"
    }
  ]
}
```

#### Assistant 历史中的 Tool Uses
```json
{
  "assistantResponseMessage": {
    "content": "文本回复",
    "toolUses": [
      {
        "toolUseId": "xxx",
        "name": "tool_name",
        "input": { ... }
      }
    ]
  }
}
```

### 响应格式

响应是 **AWS EventStream 二进制协议**，不是普通 JSON。

#### EventStream 结构
每个消息由以下部分组成：
- Prelude: total_length (4 bytes) + headers_length (4 bytes) + prelude_crc (4 bytes)
- Headers: key-value pairs (name length + name + value type + value)
- Payload: JSON body
- Message CRC: 4 bytes

#### Header 类型
- `:event-type` — 事件类型
- `:content-type` — 内容类型
- `:message-type` — 消息类型（`event` 或 `exception`）

#### 事件类型
| 事件类型 | 说明 |
|---------|------|
| `assistantResponseEvent` | 文本内容 chunk，payload: `{"content": "..."}` |
| `toolUse` | 工具调用请求 |
| `codeEvent` | 代码内容（也是文本） |
| `supplementaryWebLinksEvent` | 网页链接（可忽略） |
| `exception` | 错误 |

### Kiro 后端注入的 System Prompt

CodeWhisperer 后端会自动注入 Kiro IDE 的 system prompt，其中包含：
- `<capabilities>` 部分：声明有 web search、file operations 等能力
- `<rules>` 部分：行为规则
- 大量 IDE 工具定义（readFile, fsWrite, listDirectory, searchFiles, grepSearch, executeCommand, webSearch, fetchWebpage, getDiagnostics, readCode, getDefinition, getReferences, getTypeDefinition, smartRelocate 等）

这些工具在 Kiro IDE 内由客户端执行，但通过 kiro2chat 调用时没有执行环境。Claude 会看到这些工具定义并尝试调用，需要在 system prompt 中引导它使用实际可用的工具。

### 参考实现

- **kiro2api** (Go): `~/repos/kiro2api/`
  - `converter/codewhisperer.go` — OpenAI → CW 请求转换
  - `converter/openai.go` — CW 响应 → OpenAI 格式转换
  - `converter/tools.go` — 工具定义验证和转换
  - `parser/tool_lifecycle_manager.go` — 工具调用生命周期管理
  - `parser/sonic_streaming_aggregator.go` — 流式 JSON 聚合（处理 UTF-8 截断）
  - `parser/message_event_handlers.go` — EventStream 事件处理
  - `config/config.go` — 模型映射表

### 工具描述长度限制
- kiro2api 设置 `MaxToolDescriptionLength = 10000`
- 超长的 tool description 需要截断，否则 CW 可能拒绝请求
