# Pega Code Review MCP Server

Exposes Pega DX v1 APIs as MCP tools so Claude can fetch rule XMLs and do
full LSA-grade code reviews natively — no scripts, no GPT, just Claude.

## Tools

| Tool | API Called | Purpose |
|------|-----------|---------|
| `pega_list_branches` | `D_GetAvailableBranchesForAppStack` | List all branches, filter by app |
| `pega_get_branch_rules` | `D_BranchContent` | Get all rules in a branch |
| `pega_get_rule_xml` | `D_BranchAnalyzerAPI` | Fetch full XML of any rule by pzInsKey |
| `pega_get_referenced_rules` | `D_BranchAnalyzerAPI` (×N) | Fetch XMLs of all rules referenced by a rule |

## Running in Claude Desktop

### Step 1 -- Prerequisites

- Python 3.10+ installed
- Claude Desktop installed
- A running Pega instance (8.3-8.6, section-based UI)

### Step 2 -- Clone & Install

If this is your first time setup:

```bash
git clone https://github.com/alamaticz/Pega-Code-Review-MCP.git
cd Pega-Code-Review-MCP
pip install -r requirements.txt
```

If you already have this repo locally:

```bash
cd Pega-Code-Review-MCP
git pull origin main
pip install -r requirements.txt
```

After install, note the full absolute path to `server.py` -- you will use it in Claude Desktop config.

Windows example: `C:\Users\YourName\Pega-Code-Review-MCP\server.py`

macOS / Linux example: `/Users/yourname/Pega-Code-Review-MCP/server.py`

### Step 3 -- Edit Claude Desktop Config

Open the Claude Desktop configuration file in a text editor:

| OS | Config file location |
|----|----------------------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

If the file does not exist, create it.

Add the following (replace the `args` path and credentials with your own values).

Windows:

```json
{
  "mcpServers": {
    "pega-review": {
      "command": "python",
      "args": ["C:\\Users\\YourName\\Pega-Code-Review-MCP\\server.py"],
      "env": {
        "PEGA_BASE_URL": "https://your-server.pegacloud.net/prweb",
        "PEGA_USERNAME": "your_operator_id",
        "PEGA_PASSWORD": "your_password"
      }
    }
  }
}
```

macOS / Linux:

```json
{
  "mcpServers": {
    "pega-review": {
      "command": "python3",
      "args": ["/Users/yourname/Pega-Code-Review-MCP/server.py"],
      "env": {
        "PEGA_BASE_URL": "https://your-server.pegacloud.net/prweb",
        "PEGA_USERNAME": "your_operator_id",
        "PEGA_PASSWORD": "your_password"
      }
    }
  }
}
```

Note: If you already have other MCP servers in the config, add the `pega-review` block inside the existing `mcpServers` object -- do not create a second `mcpServers` key.

If you use a virtual environment, set `command` to your venv Python executable instead of `python` / `python3`.

### Step 4 -- Restart Claude Desktop

Fully quit and reopen Claude Desktop. The Pega review MCP tools will appear in the tools panel.

### Step 5 -- Quick verification

In Claude, run:

1. "List available MCP tools"
2. `pega_list_branches`

## Usage Flow (Code Review)

1. `pega_list_branches` — find a branch to review
2. `pega_get_branch_rules` — see all rules in the branch
3. `pega_get_rule_xml` — fetch XML for each rule to review
4. `pega_get_referenced_rules` — fetch XMLs of all referenced rules
5. Analyse everything and write the LSA review

## Add Skills in Claude Desktop

This repo already includes two packaged skills:

- `pega-lsa-review-format.skill`
- `pega-rule-doc-skill.skill`

Claude loads local skills from folders under:

```
%USERPROFILE%\.claude\skills\<skill-folder>\SKILL.md
```

### 1. Install the packaged skills (Windows PowerShell)
Run from this repo root:

```powershell
$skillsRoot = "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Directory -Force -Path $skillsRoot | Out-Null

# Install pega-lsa-review-format skill (archive contains SKILL.md at root)
$lsaDir = Join-Path $skillsRoot "pega-lsa-review-format"
New-Item -ItemType Directory -Force -Path $lsaDir | Out-Null
tar -xf .\pega-lsa-review-format.skill -C $lsaDir

# Install pega-rule-doc skill (archive contains its own folder)
tar -xf .\pega-rule-doc-skill.skill -C $skillsRoot
```

### 2. Verify the skills are installed

```powershell
Get-ChildItem "$env:USERPROFILE\.claude\skills" -Recurse -Filter SKILL.md |
  Select-Object -ExpandProperty FullName
```

You should see entries similar to:

- `%USERPROFILE%\.claude\skills\pega-lsa-review-format\SKILL.md`
- `%USERPROFILE%\.claude\skills\pega-rule-doc-skill\SKILL.md`

### 3. Restart Claude Desktop
Close and reopen Claude Desktop so it refreshes skill discovery.

### 4. Confirm in chat
In Claude, ask:

1. "What skills are available?"
2. Invoke `/pega-lsa-review-format` for review output structure
3. Invoke `/pega-rule-doc` for rule XML documentation generation

### 5. Use skills with this MCP server

- Use `/pega-lsa-review-format` before running branch/rule review with MCP tools.
- Use `/pega-rule-doc` when generating full technical documentation from exported rule XML.
