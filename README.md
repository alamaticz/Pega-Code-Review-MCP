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

## Run in Claude Desktop

### 1. Install dependencies
From this project folder, install Python dependencies:

```bash
cd C:\Users\Manoj\OneDrive\Desktop\Projects\Pega-Review-MCP
pip install -r requirements.txt
```

### 2. Set Pega credentials
Create a `.env` file in the project root:

```
PEGA_BASE_URL=xxxx
PEGA_USERNAME=xxxx
PEGA_PASSWORD=xxxx
```

### 3. (Optional) Test server locally
Run:

```bash
python server.py
```

If credentials are configured, the process will start and wait for MCP stdio requests.
Use `Ctrl+C` to stop it.

### 4. Add MCP server to Claude Desktop
Open `%APPDATA%\Claude\claude_desktop_config.json` and add this entry under `mcpServers`
(or merge it into your existing JSON):

```json
{
  "mcpServers": {
    "pega-review": {
      "command": "python",
      "args": [
        "C:\\Users\\Manoj\\OneDrive\\Desktop\\Projects\\Pega-Review-MCP\\server.py"
      ],
      "env": {
        "PEGA_BASE_URL": "xxxxx",
        "PEGA_USERNAME": "xxxxx",
        "PEGA_PASSWORD": "xxxxx"
      }
    }
  }
}
```

If you use a virtual environment, set `command` to your venv Python executable
(for example: `C:\\path\\to\\venv\\Scripts\\python.exe`).

### 5. Restart Claude Desktop
Close and reopen Claude Desktop so it loads the MCP server.

### 6. Verify tools are available
In Claude, try:

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
