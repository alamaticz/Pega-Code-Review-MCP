#!/usr/bin/env python3
"""
Pega Code Review MCP Server

Provides tools for fetching Pega rule data (branches, rules, XML, referenced rules)
to enable AI-driven LSA code reviews directly inside Claude.

Tools:
  pega_list_branches           — List all branches from D_GetAvailableBranchesForAppStack
  pega_get_branch_rules        — Get all rules in a branch from D_BranchContent
  pega_get_rule_xml            — Fetch full rule XML via D_BranchAnalyzerAPI
  pega_get_referenced_rules    — Extract referenced rules list from a rule's XML response
  pega_get_implicit_references — Parse pxRuleReferences from rule XML without extra API calls
"""

import os
import json
import base64
import sys
import xml.etree.ElementTree as ET
from typing import Optional, List
from enum import Enum

import httpx
from pydantic import BaseModel, Field, field_validator, ConfigDict
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------

mcp = FastMCP("pega_review_mcp")

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

PEGA_BASE_URL  = os.getenv("PEGA_BASE_URL", "").rstrip("/")
PEGA_USERNAME  = os.getenv("PEGA_USERNAME", "")
PEGA_PASSWORD  = os.getenv("PEGA_PASSWORD", "")
REQUEST_TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _auth() -> tuple[str, str]:
    if not PEGA_BASE_URL or not PEGA_USERNAME or not PEGA_PASSWORD:
        raise ValueError(
            "Pega credentials not configured. "
            "Set PEGA_BASE_URL, PEGA_USERNAME, PEGA_PASSWORD in your .env file."
        )
    return (PEGA_USERNAME, PEGA_PASSWORD)


def _encode_ins_key(pz_ins_key: str) -> str:
    """Base64-encode a pzInsKey for use with D_BranchAnalyzerAPI."""
    return base64.b64encode(pz_ins_key.encode("utf-8")).decode("ascii")


async def _pega_get(path: str, params: Optional[dict] = None) -> dict:
    """Single shared async GET against the Pega DX API."""
    auth = _auth()
    url  = f"{PEGA_BASE_URL}{path}"
    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.get(
            url,
            params=params,
            auth=auth,
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()


def _handle_error(e: Exception) -> str:
    """Consistent, actionable error messages."""
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 401:
            return "Error 401: Authentication failed. Check PEGA_USERNAME / PEGA_PASSWORD."
        if status == 403:
            return "Error 403: Access denied. The configured user lacks permission for this resource."
        if status == 404:
            return "Error 404: Endpoint not found. Verify PEGA_BASE_URL points to a valid Pega instance."
        if status == 503:
            return "Error 503: Pega server unavailable. The instance may be starting up or under maintenance."
        try:
            body = e.response.json()
            msg  = body.get("errors", [{}])[0].get("message", e.response.text[:200])
        except Exception:
            msg = e.response.text[:200]
        return f"Error {status}: {msg}"
    if isinstance(e, httpx.TimeoutException):
        return f"Error: Request timed out after {REQUEST_TIMEOUT}s. The Pega instance may be slow."
    if isinstance(e, ValueError):
        return f"Configuration error: {e}"
    return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

class ListBranchesInput(BaseModel):
    """Input for listing available branches."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    app_filter: Optional[str] = Field(
        default=None,
        description="Optional application name to filter branches (e.g. 'CCPM'). "
                    "If omitted, all branches across all applications are returned.",
        max_length=200,
    )
    response_format: str = Field(
        default="markdown",
        description="Output format: 'markdown' for human-readable table, 'json' for structured data.",
        pattern="^(markdown|json)$",
    )


class GetBranchRulesInput(BaseModel):
    """Input for fetching all rules inside a branch."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    branch_id: str = Field(
        ...,
        description="Branch ID exactly as returned by pega_list_branches (e.g. 'Pl-347').",
        min_length=1,
        max_length=300,
    )
    rule_type_filter: Optional[str] = Field(
        default=None,
        description="Optional rule type to filter results (e.g. 'Activity', 'Data Transform', "
                    "'Connect REST', 'Decision Table', 'Data Page'). Case-insensitive partial match.",
        max_length=100,
    )
    response_format: str = Field(
        default="markdown",
        description="Output format: 'markdown' or 'json'.",
        pattern="^(markdown|json)$",
    )


class GetRuleXmlInput(BaseModel):
    """Input for fetching a rule's full XML via D_BranchAnalyzerAPI."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    pz_ins_key: str = Field(
        ...,
        description="Full pzInsKey of the rule to fetch, exactly as shown in branch rules listing. "
                    "Format: 'RULE-OBJ-ACTIVITY ClassName RULENAME #timestamp' "
                    "(e.g. 'RULE-OBJ-ACTIVITY PDS-CCPM-WORK-RTS TRIGGERRTSREQUEST #20260319T064123.904 GMT').",
        min_length=10,
    )
    app_name: Optional[str] = Field(
        default=None,
        description="Application name as returned by pega_list_branches (e.g. 'Monitoring'). "
                    "Required for Pega instances that scope rule resolution by application.",
        max_length=200,
    )
    app_version: Optional[str] = Field(
        default=None,
        description="Application version as returned by pega_list_branches (e.g. '01.01.01'). "
                    "Required alongside app_name for application-scoped rule resolution.",
        max_length=50,
    )


class GetReferencedRulesInput(BaseModel):
    """Input for extracting the referenced rules list from a rule's API response."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    pz_ins_key: str = Field(
        ...,
        description="Full pzInsKey of the rule whose referenced rules you want to retrieve. "
                    "The server fetches the rule and parses the referenced_rule field.",
        min_length=10,
    )
    rule_type_filter: Optional[str] = Field(
        default=None,
        description="Optional rule type filter on the referenced rules "
                    "(e.g. 'Activity', 'Data Transform', 'Connect REST'). Case-insensitive.",
        max_length=100,
    )
    app_name: Optional[str] = Field(
        default=None,
        description="Application name as returned by pega_list_branches (e.g. 'Monitoring'). "
                    "Required for Pega instances that scope rule resolution by application.",
        max_length=200,
    )
    app_version: Optional[str] = Field(
        default=None,
        description="Application version as returned by pega_list_branches (e.g. '01.01.01'). "
                    "Required alongside app_name for application-scoped rule resolution.",
        max_length=50,
    )


# ---------------------------------------------------------------------------
# Tool 1: pega_list_branches
# ---------------------------------------------------------------------------

@mcp.tool(
    name="pega_list_branches",
    annotations={
        "title": "List Pega Branches",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pega_list_branches(params: ListBranchesInput) -> str:
    """List all available development branches from the Pega application stack.

    Calls D_GetAvailableBranchesForAppStack and returns branch IDs grouped by
    application. Use this as the first step in a code review to discover which
    branches exist, then pick one to inspect with pega_get_branch_rules.

    Args:
        params (ListBranchesInput):
            - app_filter (Optional[str]): Filter by application name (e.g. 'CCPM')
            - response_format (str): 'markdown' or 'json'

    Returns:
        str: List of branches with their IDs and application names.

        JSON schema when response_format='json':
        {
            "total": int,
            "branches": [
                {
                    "branch_id":   str,   # e.g. "Pl-347"
                    "app_name":    str,   # e.g. "CCPM"
                    "app_version": str    # e.g. "01-01-01"
                }
            ]
        }

    Examples:
        - List all branches:          params with no app_filter
        - List CCPM branches only:    params with app_filter="CCPM"
    """
    try:
        data    = await _pega_get("/api/v1/data/D_GetAvailableBranchesForAppStack")
        results = data.get("pxResults", [])

        branches = []
        for row in results:
            bp = row.get("pxPages", {}).get("Branches", {})
            bid = bp.get("pyBranchID", "")
            if not bid:
                continue
            app = bp.get("pzAppName", "")
            ver = bp.get("pzAppVersion", "")
            if params.app_filter and params.app_filter.lower() not in app.lower():
                continue
            branches.append({"branch_id": bid, "app_name": app, "app_version": ver})

        if not branches:
            return (
                f"No branches found"
                + (f" for application '{params.app_filter}'." if params.app_filter else ".")
            )

        if params.response_format == "json":
            return json.dumps({"total": len(branches), "branches": branches}, indent=2)

        # Markdown
        lines = [f"## Pega Branches ({len(branches)} found)\n"]
        current_app = None
        for b in sorted(branches, key=lambda x: (x["app_name"], x["branch_id"])):
            if b["app_name"] != current_app:
                current_app = b["app_name"]
                lines.append(f"\n### App: {current_app}")
            lines.append(f"- `{b['branch_id']}` (v{b['app_version']})")
        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Tool 2: pega_get_branch_rules
# ---------------------------------------------------------------------------

@mcp.tool(
    name="pega_get_branch_rules",
    annotations={
        "title": "Get Rules in a Pega Branch",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pega_get_branch_rules(params: GetBranchRulesInput) -> str:
    """Fetch all rules contained in a Pega development branch.

    Calls D_BranchContent?branchID=... and returns the full rule listing
    with rule names, classes, types, rulesets, and pzInsKeys. The pzInsKey
    values are required inputs for pega_get_rule_xml and pega_get_referenced_rules.

    Args:
        params (GetBranchRulesInput):
            - branch_id (str):             Branch ID (e.g. 'Pl-347')
            - rule_type_filter (Optional[str]): Filter by rule type (e.g. 'Activity')
            - response_format (str):       'markdown' or 'json'

    Returns:
        str: List of rules with names, classes, types, and pzInsKeys.

        JSON schema when response_format='json':
        {
            "total": int,
            "branch_id": str,
            "rules": [
                {
                    "rule_name":    str,
                    "class_name":   str,
                    "rule_type":    str,
                    "ruleset":      str,
                    "last_updated": str,
                    "pz_ins_key":   str   # Use this for pega_get_rule_xml
                }
            ]
        }

    Examples:
        - All rules in Pl-347:              params with branch_id="Pl-347"
        - Only Activities in Pl-347:        params with branch_id="Pl-347", rule_type_filter="Activity"
        - Only Data Transforms in Pl-347:   params with branch_id="Pl-347", rule_type_filter="Data Transform"
    """
    try:
        data  = await _pega_get("/api/v1/data/D_BranchContent", params={"branchID": params.branch_id})
        raw   = data.get("pxResults") or []

        rules = []
        for r in raw:
            rule_type = r.get("pyClassLabel") or r.get("pyClass") or r.get("ruleType") or ""
            if params.rule_type_filter and params.rule_type_filter.lower() not in rule_type.lower():
                continue
            rules.append({
                "rule_name":    r.get("pyRuleName") or r.get("name") or r.get("pxInsName", ""),
                "class_name":   r.get("pyClassName") or r.get("className") or "",
                "rule_type":    rule_type,
                "ruleset":      r.get("pyRuleSet") or r.get("ruleSetName") or "",
                "last_updated": r.get("pxUpdateDateTime") or r.get("pxSaveDateTime") or "",
                "pz_ins_key":   r.get("pzInsKey") or r.get("insKey") or "",
            })

        if not rules:
            msg = f"No rules found in branch '{params.branch_id}'"
            if params.rule_type_filter:
                msg += f" matching type '{params.rule_type_filter}'"
            return msg + "."

        if params.response_format == "json":
            return json.dumps({"total": len(rules), "branch_id": params.branch_id, "rules": rules}, indent=2)

        # Markdown
        lines = [f"## Rules in Branch: `{params.branch_id}` ({len(rules)} rules)\n"]
        if params.rule_type_filter:
            lines.append(f"*Filtered by type: {params.rule_type_filter}*\n")

        current_type = None
        for r in sorted(rules, key=lambda x: (x["rule_type"], x["rule_name"])):
            if r["rule_type"] != current_type:
                current_type = r["rule_type"]
                lines.append(f"\n### {current_type or 'Unknown Type'}")
            lines.append(
                f"- **{r['rule_name']}** | Class: `{r['class_name']}` | "
                f"RuleSet: `{r['ruleset']}` | Updated: {r['last_updated'][:19]}\n"
                f"  `pzInsKey: {r['pz_ins_key']}`"
            )
        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Tool 3: pega_get_rule_xml
# ---------------------------------------------------------------------------

@mcp.tool(
    name="pega_get_rule_xml",
    annotations={
        "title": "Fetch Pega Rule XML",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pega_get_rule_xml(params: GetRuleXmlInput) -> str:
    """Fetch the full XML definition of a Pega rule via D_BranchAnalyzerAPI.

    Returns the complete rule_info XML which contains all steps, mappings,
    conditions, parameters, and metadata needed for a thorough LSA code review.
    Also includes the referenced_rule list which identifies all rules called
    or referenced by this rule.

    Use pega_get_referenced_rules to fetch the XML of each referenced rule
    for a complete call-chain review.

    Args:
        params (GetRuleXmlInput):
            - pz_ins_key (str): Full pzInsKey of the rule (from pega_get_branch_rules output)

    Returns:
        str: JSON object containing:
        {
            "pz_ins_key":        str,   # The key that was fetched
            "rule_name":         str,   # Parsed rule name
            "rule_class":        str,   # Applies-To class
            "format":            str,   # "XML" or "JSON"
            "xml_size_chars":    int,   # Size of the raw XML
            "rule_info":         str,   # Full raw XML/JSON — analyse this for the code review
            "referenced_rules":  list   # List of referenced rule entries (name, type, pzInsKey)
        }

    Examples:
        - Fetch an Activity:       pz_ins_key="RULE-OBJ-ACTIVITY PDS-CCPM-WORK-RTS TRIGGERRTSREQUEST #20260319T064123.904 GMT"
        - Fetch a Data Transform:  pz_ins_key="RULE-OBJ-MODEL PDS-CCPM-WORK-RTS MAPRTSREQUEST_PROVIDER #20260319T082314.398 GMT"
    """
    try:
        encoded = _encode_ins_key(params.pz_ins_key)
        api_params: dict = {"RuleInsKey": encoded}
        if params.app_name:
            api_params["ApplicationName"] = params.app_name
        if params.app_version:
            api_params["ApplicationVersion"] = params.app_version
        data    = await _pega_get("/api/v1/data/D_BranchAnalyzerAPI", params=api_params)

        rules = data.get("response_page", {}).get("rules", []) or data.get("rules", [])
        if not rules:
            return (
                f"No rule content returned for pzInsKey: {params.pz_ins_key}\n"
                "Check that the key is correct and the rule exists in the Pega instance."
            )

        rule        = rules[0]
        rule_info   = rule.get("rule_info", "")
        ref_raw     = rule.get("referenced_rule", "")

        # Parse referenced rules if present
        referenced = []
        if ref_raw:
            try:
                ref_data = json.loads(ref_raw) if isinstance(ref_raw, str) else ref_raw
                for entry in ref_data.get("pxResults", []):
                    referenced.append({
                        "rule_name":  entry.get("pyRuleName", ""),
                        "rule_type":  entry.get("pyRuleType", ""),
                        "class_name": entry.get("pyClassName", ""),
                        "pz_ins_key": entry.get("pzInsKey", ""),
                    })
            except Exception:
                pass

        # Extract basic identity from XML
        import re
        def _xtag(tag: str) -> str:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", rule_info, re.DOTALL)
            return m.group(1).strip() if m else ""

        is_xml    = rule_info.lstrip().startswith("<")
        rule_name = _xtag("pyRuleName") or rule.get("name", "")
        rule_cls  = _xtag("pyClassName") or rule.get("type", "")

        result = {
            "pz_ins_key":       params.pz_ins_key,
            "rule_name":        rule_name,
            "rule_class":       rule_cls,
            "format":           "XML" if is_xml else "JSON",
            "xml_size_chars":   len(rule_info),
            "rule_info":        rule_info,
            "referenced_rules": referenced,
        }
        return json.dumps(result, indent=2, ensure_ascii=False)

    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Tool 4: pega_get_referenced_rules
# ---------------------------------------------------------------------------

@mcp.tool(
    name="pega_get_referenced_rules",
    annotations={
        "title": "Get Referenced Rules XML",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pega_get_referenced_rules(params: GetReferencedRulesInput) -> str:
    """Fetch the full XML of all rules referenced by a given Pega rule.

    First calls D_BranchAnalyzerAPI to get the source rule and extract its
    referenced_rule list, then fetches the XML of each referenced rule in
    the list. Returns all XMLs in a single response for call-chain analysis.

    Use this after pega_get_rule_xml to drill into every rule called or
    referenced by the primary rule being reviewed.

    Args:
        params (GetReferencedRulesInput):
            - pz_ins_key (str):             pzInsKey of the source rule
            - rule_type_filter (Optional[str]): Only fetch referenced rules of this type

    Returns:
        str: JSON array of fetched referenced rules:
        [
            {
                "rule_name":      str,
                "rule_type":      str,
                "class_name":     str,
                "pz_ins_key":     str,
                "format":         str,    # "XML" or "JSON"
                "xml_size_chars": int,
                "rule_info":      str,    # Full XML — analyse this for the review
                "fetch_status":   str     # "ok" or "error: ..."
            }
        ]

    Examples:
        - All referenced rules of an Activity:
            pz_ins_key="RULE-OBJ-ACTIVITY PDS-CCPM-WORK-RTS TRIGGERRTSREQUEST #20260319T064123.904 GMT"
        - Only Data Transform referenced rules:
            pz_ins_key="...", rule_type_filter="Data Transform"
    """
    try:
        # Step 1: fetch the source rule to get its referenced_rule list
        encoded  = _encode_ins_key(params.pz_ins_key)
        api_params: dict = {"RuleInsKey": encoded}
        if params.app_name:
            api_params["ApplicationName"] = params.app_name
        if params.app_version:
            api_params["ApplicationVersion"] = params.app_version
        data     = await _pega_get("/api/v1/data/D_BranchAnalyzerAPI", params=api_params)

        rules = data.get("response_page", {}).get("rules", []) or data.get("rules", [])
        if not rules:
            return f"Error: Could not fetch source rule for pzInsKey: {params.pz_ins_key}"

        ref_raw = rules[0].get("referenced_rule", "")
        if not ref_raw:
            return f"No referenced rules found for: {params.pz_ins_key}"

        # Parse referenced rule list
        try:
            ref_data = json.loads(ref_raw) if isinstance(ref_raw, str) else ref_raw
            ref_list = ref_data.get("pxResults", [])
        except Exception:
            return f"Error: Could not parse referenced_rule field for: {params.pz_ins_key}"

        # Step 2: filter by type if requested
        if params.rule_type_filter:
            ref_list = [
                r for r in ref_list
                if params.rule_type_filter.lower() in r.get("pyRuleType", "").lower()
            ]

        if not ref_list:
            msg = f"No referenced rules found for '{params.pz_ins_key}'"
            if params.rule_type_filter:
                msg += f" with type filter '{params.rule_type_filter}'"
            return msg + "."

        # Step 3: fetch XML for each referenced rule concurrently
        import re
        import asyncio

        async def _fetch_one(entry: dict) -> dict:
            ref_key  = entry.get("pzInsKey", "")
            r_name   = entry.get("pyRuleName", "")
            r_type   = entry.get("pyRuleType", "")
            r_class  = entry.get("pyClassName", "")
            result   = {
                "rule_name":      r_name,
                "rule_type":      r_type,
                "class_name":     r_class,
                "pz_ins_key":     ref_key,
                "format":         "unknown",
                "xml_size_chars": 0,
                "rule_info":      "",
                "fetch_status":   "skipped — no pzInsKey",
            }
            if not ref_key:
                return result
            try:
                enc        = _encode_ins_key(ref_key)
                ref_params: dict = {"RuleInsKey": enc}
                if params.app_name:
                    ref_params["ApplicationName"] = params.app_name
                if params.app_version:
                    ref_params["ApplicationVersion"] = params.app_version
                resp = await _pega_get("/api/v1/data/D_BranchAnalyzerAPI", params=ref_params)
                sub  = resp.get("response_page", {}).get("rules", []) or resp.get("rules", [])
                if sub:
                    ri = sub[0].get("rule_info", "")
                    result["rule_info"]      = ri
                    result["xml_size_chars"] = len(ri)
                    result["format"]         = "XML" if ri.lstrip().startswith("<") else "JSON"
                    result["fetch_status"]   = "ok"
                else:
                    result["fetch_status"] = "error: no rule content in response"
            except Exception as ex:
                result["fetch_status"] = f"error: {_handle_error(ex)}"
            return result

        fetched = await asyncio.gather(*[_fetch_one(entry) for entry in ref_list])
        return json.dumps(list(fetched), indent=2, ensure_ascii=False)

    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Tool 5: pega_get_implicit_references
# ---------------------------------------------------------------------------

class GetImplicitReferencesInput(BaseModel):
    """Input for parsing pxRuleReferences from a rule XML string."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    rule_xml: str = Field(
        ...,
        description="Full raw XML string of a Pega rule (as returned in rule_info from pega_get_rule_xml). "
                    "Works for any rule type: Activity, Data Transform, Collection, Decision Table, Data Page, etc.",
        min_length=10,
    )


@mcp.tool(
    name="pega_get_implicit_references",
    annotations={
        "title": "Parse Implicit Rule References from XML",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def pega_get_implicit_references(params: GetImplicitReferencesInput) -> str:
    """Parse all implicitly referenced rules from pxRuleReferences in a Pega rule XML.

    Extracts the pxRuleReferences repeating page list that Pega automatically
    populates when any rule is saved. This is an offline parse — no API calls
    are made. Works identically for Activity, Data Transform, Collection,
    Decision Table, Data Page, Connect REST, or any other rule type.

    Each entry in the output uses the raw Pega internal keys (not human-readable
    labels) so they can be passed directly to Pega APIs.

    Args:
        params (GetImplicitReferencesInput):
            - rule_xml (str): Full XML string from pega_get_rule_xml's rule_info field

    Returns:
        str: JSON array of referenced rule entries:
        [
            {
                "RuleName": str,    # pyRuleName — display name of the referenced rule
                "RuleType": str     # pxRuleObjClass — e.g. "Rule-Obj-Activity"
            }
        ]

    Examples:
        - Parse references from an Activity XML:
            rule_xml="<pega:RuleSet ...>...</pega:RuleSet>"
        - Parse references from a Data Transform XML:
            rule_xml="<pega:RuleSet ...>...</pega:RuleSet>"
    """
    try:
        root = ET.fromstring(params.rule_xml)
    except ET.ParseError as e:
        return f"Error: Could not parse XML — {e}"

    results = []
    seen: set = set()

    for row in root.findall(".//pxRuleReferences/rowdata"):
        rule_name  = (row.findtext("pyRuleName")     or "").strip()
        obj_class  = (row.findtext("pxRuleObjClass") or "").strip()
        class_name = (row.findtext("pxRuleClassName") or "").strip()

        if not rule_name or not obj_class:
            continue

        dedup_key = (rule_name, obj_class)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        results.append({
            "RuleName": rule_name,
            "RuleType": obj_class,
        })

    if not results:
        return json.dumps([])

    return json.dumps(results, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    missing = [k for k in ("PEGA_BASE_URL", "PEGA_USERNAME", "PEGA_PASSWORD") if not os.getenv(k)]
    if missing:
        print(
            f"WARNING: Missing environment variables: {', '.join(missing)}\n"
            "Set them in your .env file before using the Pega tools.",
            file=sys.stderr,
        )
    mcp.run()
