# CoPilot Session Schema

## Overview

CoPilot chat sessions are stored as individual JSON files in the VS Code `workspaceStorage` directory. Each session represents a complete conversation between a user and the CoPilot AI agent within a specific workspace context.

**Format:** JSON (not JSONL like Codex)

**File Structure:** Single JSON object per file

**Location:** `C:\Users\<username>\AppData\Roaming\Code\User\workspaceStorage\<workspace-hash>\chatSessions\<session-uuid>.json`

**File Count:** One file per chat session (multiple files may exist in the same workspace)

______________________________________________________________________

## Root Session Object

The top-level structure of a CoPilot session JSON file.

### Root Session Fields

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `version` | integer | Session format version (currently `3`) | No |
| `requesterUsername` | string | Name of the user requesting assistance | Yes\* |
| `requesterAvatar` | string (URI) | Avatar image URI for the user | Yes |
| `responderUsername` | string | Name of the CoPilot agent (typically "Copilot") | No |
| `responderAvatar` | string (URI) | Avatar image URI for the agent | No |
| `requests` | array | Array of request-response exchanges | Yes\* |

*Fields marked "Yes*" may contain workspace paths, file references, or code artifacts that should be considered sensitive for redaction purposes.

### Example

```json
{
  "version": 3,
  "requesterUsername": "john_doe",
  "requesterAvatar": "data:image/svg+xml;...",
  "responderUsername": "Copilot",
  "responderAvatar": "data:image/svg+xml;...",
  "requests": [...]
}
```

______________________________________________________________________

## Request Object

Represents a single user question or interaction and the corresponding response(s) from CoPilot.

### Request Object Fields

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `requestId` | string | Unique identifier for this request (UUID format) | No |
| `message` | Message | The user's message/question | Yes |
| `variableData` | VariableData | Context variables (files, workspace, selections) | Yes |
| `response` | array | Array of ResponsePart objects representing CoPilot's reply | Yes |

### Request Example

```json
{
  "requestId": "abc123-def456-ghi789",
  "message": {...},
  "variableData": {...},
  "response": [...]
}
```

______________________________________________________________________

## Message Object

Represents the user's message or query.

### Message Object Fields

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `parts` | array | Array of MessagePart objects | Yes |

### MessagePart Object

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `text` | string | Plain text content of the message | Yes |
| `kind` | string | Type of message part (e.g., "text") | No |
| `range` | Range (optional) | Text range reference (start/end lines and chars) | No |
| `editorRange` | EditorRange (optional) | Editor-specific range with file reference | Yes |

### Range Object

| Field | Type | Description |
| --- | --- | --- |
| `startLineNumber` | integer | Starting line number (0-indexed) |
| `startColumn` | integer | Starting column (0-indexed) |
| `endLineNumber` | integer | Ending line number (0-indexed) |
| `endColumn` | integer | Ending column (0-indexed) |

### EditorRange Object

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `uri` | URI | File URI being referenced | Yes |
| `range` | Range | Position in the file | No |

### Message Example

```json
{
  "message": {
    "parts": [
      {
        "text": "Can you help me fix this function?",
        "kind": "text"
      },
      {
        "editorRange": {
          "uri": {
            "$mid": 1,
            "path": "/c:/Users/john/project/main.py",
            "scheme": "file",
            "fsPath": "c:\\Users\\john\\project\\main.py"
          },
          "range": {
            "startLineNumber": 10,
            "startColumn": 0,
            "endLineNumber": 20,
            "endColumn": 0
          }
        }
      }
    ]
  }
}
```

______________________________________________________________________

## VariableData Object

Context information about the current workspace and selection.

### VariableData Object Fields

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `variables` | object | Map of variable names to Variable objects | Yes |

### Variable Object

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `kind` | string | Variable type (e.g., "file", "selection", "workspace") | No |
| `value` | string OR URI OR object | The variable value (type depends on kind) | Yes |

### Variable Kinds

- **`file`**: Currently selected file (URI)
- **`selection`**: Currently selected text or range (string or Range object)
- **`workspace`**: Current workspace directory (URI)

### VariableData Example

```json
{
  "variableData": {
    "variables": {
      "selectedFile": {
        "kind": "file",
        "value": {
          "$mid": 1,
          "path": "/c:/Users/john/project/utils.py",
          "scheme": "file",
          "fsPath": "c:\\Users\\john\\project\\utils.py"
        }
      },
      "selectedText": {
        "kind": "selection",
        "value": "def process_data():"
      },
      "workspaceFolder": {
        "kind": "workspace",
        "value": {
          "$mid": 2,
          "path": "/c:/Users/john/project",
          "scheme": "file",
          "fsPath": "c:\\Users\\john\\project"
        }
      }
    }
  }
}
```

______________________________________________________________________

## URI Object

Represents a file or HTTP resource reference.

### URI Object Fields

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `$mid` | integer | Marker ID for internal serialization | No |
| `path` | string | POSIX-style path | Yes |
| `scheme` | string | URI scheme (e.g., "file", "https") | No |
| `fsPath` (optional) | string | Windows filesystem path | Yes |
| `authority` (optional) | string | Authority component (for https) | Yes |

### URI Example

```json
{
  "$mid": 1,
  "path": "/c:/Users/john/project/file.py",
  "scheme": "file",
  "fsPath": "c:\\Users\\john\\project\\file.py"
}
```

______________________________________________________________________

## Response Object

Array of ResponsePart objects representing CoPilot's response.

### ResponsePart Types

#### Text Response

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `kind` | string | Always "text" | No |
| `text` | string | The response text (markdown, code, explanation) | Yes |

#### Tool Invocation Response

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `kind` | string | Always "toolInvocation" | No |
| `toolInvocation` | ToolInvocation | Details of the tool being invoked | Yes |

#### Reference Response

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `kind` | string | Always "reference" | No |
| `reference` | object | Reference to external content | Yes |

#### Edit Response

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `kind` | string | Always "textEdit" | No |
| `edits` | TextEditGroup | Group of text edits to be applied | Yes |

#### Undo Stop Response

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `kind` | string | Always "undoStop" | No |

### ToolInvocation Object

Represents a tool action that CoPilot is requesting to be performed.

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `toolName` | string | Name of the tool (e.g., "copilot_readFile", "copilot_replaceString") | No |
| `invocationId` | string | Unique identifier for this invocation | No |
| `arguments` | object | Tool-specific arguments | Yes |

### Common Tool Names

| Tool | Purpose | Sensitive Arguments |
| --- | --- | --- |
| `copilot_readFile` | Read file contents | `filePath`, `range` |
| `copilot_replaceString` | Replace text in file | `filePath`, `newString`, `oldString` |
| `copilot_createFile` | Create new file | `filePath`, `content` |
| `copilot_deleteFile` | Delete file | `filePath` |
| `copilot_createTerminal` | Create terminal session | Command strings, paths |
| `copilot_runCommand` | Execute shell/PowerShell command | Commands with file paths |

### TextEditGroup Object

| Field | Type | Description | Sensitive |
| --- | --- | --- | --- |
| `uri` | URI | File being edited | Yes |
| `edits` | array | Array of text edit objects | Yes |

### Response Example

```json
{
  "response": [
    {
      "kind": "text",
      "text": "I can help you optimize that function. Here's a better approach:"
    },
    {
      "kind": "toolInvocation",
      "toolInvocation": {
        "toolName": "copilot_readFile",
        "invocationId": "read-1",
        "arguments": {
          "filePath": "/c:/Users/john/project/main.py",
          "range": {
            "startLineNumber": 10,
            "endLineNumber": 20
          }
        }
      }
    },
    {
      "kind": "textEdit",
      "edits": {
        "uri": {
          "$mid": 1,
          "path": "/c:/Users/john/project/main.py",
          "scheme": "file",
          "fsPath": "c:\\Users\\john\\project\\main.py"
        },
        "edits": [
          {
            "range": {
              "startLineNumber": 10,
              "startColumn": 0,
              "endLineNumber": 15,
              "endColumn": 0
            },
            "text": "def optimized_function():\n    # Improved implementation\n    pass\n"
          }
        ]
      }
    },
    {
      "kind": "undoStop"
    }
  ]
}
```

______________________________________________________________________

## Key Differences from Codex Sessions

| Aspect | CoPilot | Codex |
| --- | --- | --- |
| **Format** | Single JSON per session | JSONL (one object per line) |
| **Storage** | `workspaceStorage/*/chatSessions/` | `.codex/sessions/YYYY/MM/DD/` |
| **Structure** | Flat object with requests array | Multiple event objects over time |
| **Context** | Rich variableData (files, selections) | Implicit from logs |
| **Responses** | Multiple response kinds (tool, edit, text) | Single message format |
| **Tool Actions** | Explicit toolInvocation objects | Inferred from content |
| **Frequency** | One file per conversation | Multiple files per day |

______________________________________________________________________

## Redaction Points

When preparing CoPilot session data for transparency reports, redact the following sensitive information:

### Always Redact

1. **File System Paths**

   - `path`, `fsPath` in URI objects
   - `filePath` in tool invocation arguments
   - All references in `variableData`

1. **Code Content**

   - Code snippets in message text
   - `newString`, `oldString` in replace operations
   - Edit contents in textEdit responses

1. **User Identity**

   - `requesterUsername`
   - Potentially `requesterAvatar` (if personally identifiable)

1. **Workspace Details**

   - Workspace folder paths
   - Selected file names and paths

### Consider Redacting

1. **Tool Arguments** that reveal implementation details
1. **Command Strings** in terminal invocations (may contain secrets)
1. **File Names** that reveal project structure or sensitive topics

### Example Redaction

```json
{
  "message": {
    "parts": [
      {
        "text": "[REDACTED CODE SNIPPET]",
        "kind": "text"
      },
      {
        "editorRange": {
          "uri": {
            "fsPath": "[REDACTED PATH]"
          },
          "range": {...}
        }
      }
    ]
  }
}
```

______________________________________________________________________

## Configuration

CoPilot session parsing is configured in `user/config.toml`:

```toml
[sessions]
# CoPilot root path (typically auto-detected)
copilot_root = "C:\\Users\\<username>\\AppData\\Roaming\\Code\\User\\workspaceStorage"

[agents.copilot]
# Enable CoPilot session ingestion
enabled = true

# Root path (can override sessions.copilot_root)
root_path = "C:\\Users\\<username>\\AppData\\Roaming\\Code\\User\\workspaceStorage"

# Batch size for processing
batch_size = 100

# Optional workspace ID filter (ingest only matching workspace)
workspace_id = null

# Preserve raw JSON alongside parsed data
preserve_raw_json = true
```

______________________________________________________________________

## Usage in Code

### Discovering CoPilot Sessions

```python
from src.agents.copilot import discover_copilot_sessions
from pathlib import Path

root = Path("C:\\Users\\user\\AppData\\Roaming\\Code\\User\\workspaceStorage")
sessions = discover_copilot_sessions(root)
# Returns: [Path(...session1.json), Path(...session2.json), ...]
```

### Parsing a Session

```python
from src.agents.copilot import parse_session_from_file

session = parse_session_from_file(Path("session.json"))
print(session.version)
print(session.requesterUsername)
for request in session.requests:
    print(f"Request {request.requestId}:")
    for response_part in request.response:
        print(f"  - {response_part.kind}")
```

### Accessing Tool Invocations

```python
for request in session.requests:
    for response_part in request.response:
        if response_part.kind == "toolInvocation":
            tool = response_part.toolInvocation
            print(f"{tool.toolName}: {tool.arguments}")
```

______________________________________________________________________

## Error Handling

The CoPilot parser raises `CoPilotParseError` for:

- Missing or corrupted JSON files
- Invalid session structure
- Missing required fields
- File permission issues

Example:

```python
from src.agents.copilot import parse_session_from_file, CoPilotParseError

try:
    session = parse_session_from_file(Path("session.json"))
except CoPilotParseError as e:
    print(f"Failed to parse session: {e}")
```

______________________________________________________________________

## Related Documentation

- [Architecture Overview](architecture.md) - System design and data flow
- [Redaction Rules](redaction_rules.md) - Comprehensive redaction strategy
- [CLI Reference](cli.md) - Command-line tools for ingestion

______________________________________________________________________

Last updated: 2025-11-23
