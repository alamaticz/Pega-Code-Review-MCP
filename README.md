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
PEGA_BASE_URL=https://pdsllc-dt1.pegacloud.io/prweb
PEGA_USERNAME=Admin@LogAnalyzer
PEGA_PASSWORD=rules@123
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
        "PEGA_BASE_URL": "https://pdsllc-dt1.pegacloud.io/prweb",
        "PEGA_USERNAME": "Admin@LogAnalyzer",
        "PEGA_PASSWORD": "rules@123"
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

## Adding Skills Later

Drop `.skill` files into `../skills/` for rule-type-specific review checklists
(Activity, Data Transform, Connect REST, etc.) and instruct Claude to use them
during review.
