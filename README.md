# memo

`memo` is a single-file, zero-dependency MCP server for sharing local memory across Claude Code, Codex, Cursor, and other MCP clients.

It stores graph-shaped memories in a local JSON file:

```text
~/.ai-memory/memory.json
```

## What it does

- Stores memories as nodes with optional edges.
- Recalls matching memories with nearby related nodes.
- Supports manual linking and pruning.
- Generates a local HTML memory map.
- Can distill memories into Agent Skills.
- Registers itself with Claude Code and Codex through the `install` command.

## Important install notice

Running `install` will register the MCP server and modify these user configuration files:

```text
~/.claude/CLAUDE.md
~/.codex/AGENTS.md
```

It writes a marked block between:

```text
<!-- memo:begin -->
<!-- memo:end -->
```

The block is updated in place on later installs.

## Install

Download the script:

```bash
curl -O https://raw.githubusercontent.com/17316119775-lab/memo-mcp/main/memo.py
```

Run install:

```bash
python3 memo.py install
```

On Windows, use `python` instead of `python3`.

## Manual registration

If you do not want to use `install`, register the MCP server manually:

```bash
claude mcp add memo --scope user -- python3 /absolute/path/to/memo.py
codex mcp add memo -- python3 /absolute/path/to/memo.py
```

## Daily use

Use natural language in an MCP client:

```text
记住：这个项目的关键口径是……
recall 项目名
#3 和 #7 有关
忘掉 #5
沉淀：项目名
```

Generate a local memory map:

```bash
python3 memo.py map
```

Output:

```text
~/.ai-memory/map.html
```

## Data location

Default:

```text
~/.ai-memory
```

Override with:

```bash
MEMO_DIR=/path/to/memory python3 memo.py
```

## Requirements

- Python 3
- No third-party Python packages

# memo

`memo` is a single-file, zero-dependency MCP server for sharing local memory across Claude Code, Codex, Cursor, and other MCP clients.

It stores graph-shaped memories in a local JSON file:

```text
~/.ai-memory/memory.json
```

## What it does

- Stores memories as nodes with optional edges.
- Recalls matching memories with nearby related nodes.
- Supports manual linking and pruning.
- Generates a local HTML memory map.
- Can distill memories into Agent Skills.
- Registers itself with Claude Code and Codex through the `install` command.

## Important install notice

Running `install` will register the MCP server and modify these user configuration files:

```text
~/.claude/CLAUDE.md
~/.codex/AGENTS.md
```

It writes a marked block between:

```text
<!-- memo:begin -->
<!-- memo:end -->
```

The block is updated in place on later installs.

## Install

Download the script:

```bash
curl -O https://raw.githubusercontent.com/OWNER/REPO/main/memo.py
```

Run install:

```bash
python3 memo.py install
```

On Windows, use `python` instead of `python3`.

## Manual registration

If you do not want to use `install`, register the MCP server manually:

```bash
claude mcp add memo --scope user -- python3 /absolute/path/to/memo.py
codex mcp add memo -- python3 /absolute/path/to/memo.py
```

## Daily use

Use natural language in an MCP client:

```text
记住：这个项目的关键口径是……
recall 项目名
#3 和 #7 有关
忘掉 #5
沉淀：项目名
```

Generate a local memory map:

```bash
python3 memo.py map
```

Output:

```text
~/.ai-memory/map.html
```

## Data location

Default:

```text
~/.ai-memory
```

Override with:

```bash
MEMO_DIR=/path/to/memory python3 memo.py
```

## Requirements

- Python 3
- No third-party Python packages

