"""FastAPI graph viewer API — SurrealDB backend."""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Accred Graph Viewer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SURREAL_URL = os.environ.get("SURREAL_URL", "http://surrealdb:8000")
SURREAL_NS = os.environ.get("SURREAL_NS", "accred")
SURREAL_DB = os.environ.get("SURREAL_DB", "accred")
SURREAL_USER = os.environ.get("SURREAL_USER", "root")
SURREAL_PASS = os.environ.get("SURREAL_PASS", "root")

_auth = base64.b64encode(f"{SURREAL_USER}:{SURREAL_PASS}".encode()).decode()
_HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Basic {_auth}",
    "surreal-ns": SURREAL_NS,
    "surreal-db": SURREAL_DB,
}

# ---- edge topology -------------------------------------------------------

_OUTGOING: dict[str, list[str]] = {
    "certificate":                  ["has_supplement", "has_decision", "in_region", "has_actual_education_organization"],
    "supplement":                   ["has_educational_program", "has_actual_education_organization"],
    "educational_program":          ["has_education_level"],
    "actual_education_organization":["in_region", "offers_education_level"],
    "educational_level":            [],
    "region":                       [],
    "decision":                     [],
}
_INCOMING: dict[str, list[str]] = {
    "certificate":                  [],
    "supplement":                   ["has_supplement"],
    "educational_program":          ["has_educational_program"],
    "educational_level":            ["has_education_level", "offers_education_level"],
    "region":                       ["in_region"],
    "actual_education_organization":["has_actual_education_organization"],
    "decision":                     ["has_decision"],
}
_EDGE_LABELS: dict[str, str] = {
    "has_supplement":                   "приложение",
    "has_decision":                     "решение",
    "in_region":                        "регион",
    "has_actual_education_organization":"ОО",
    "has_educational_program":          "программа",
    "has_education_level":              "уровень",
    "offers_education_level":           "предлагает",
}
_TABLE_LABELS: dict[str, str] = {
    "certificate":                  "Свидетельство",
    "supplement":                   "Приложение",
    "educational_program":          "Программа",
    "educational_level":            "Уровень",
    "region":                       "Регион",
    "actual_education_organization":"ОО",
    "decision":                     "Решение",
}

# ---- helpers -------------------------------------------------------------

def _rec_id(table: str, key: str) -> str:
    escaped = key.replace("\\", "\\\\").replace("`", "\\`")
    return f"{table}:`{escaped}`"


def _extract_id(val: Any) -> str:
    if isinstance(val, dict):
        return str(val.get("id", ""))
    return str(val) if val is not None else ""


def _id_to_parts(sid: str) -> tuple[str, str]:
    s = str(sid)
    if ":" not in s:
        return s, s
    table, rest = s.split(":", 1)
    key = rest.strip("`")
    return table.strip(), key.strip()


def _node_label(table: str, r: dict) -> str:
    if table == "certificate":
        return r.get("EduOrgShortName") or r.get("EduOrgFullName") or _extract_id(r.get("id"))
    if table == "supplement":
        return r.get("Number") or _extract_id(r.get("id"))
    if table == "educational_program":
        code = r.get("ProgrammCode") or ""
        name = r.get("ProgrammName") or ""
        return f"{code} {name}".strip() or _extract_id(r.get("id"))
    if table in ("educational_level", "region"):
        return r.get("name") or _extract_id(r.get("id"))
    if table == "actual_education_organization":
        return r.get("ShortName") or r.get("FullName") or _extract_id(r.get("id"))
    if table == "decision":
        return r.get("DecisionTypeName") or _extract_id(r.get("id"))
    return _extract_id(r.get("id"))


def _to_cy_node(record: dict) -> dict:
    sid = _extract_id(record.get("id"))
    table, _ = _id_to_parts(sid)
    return {
        "data": {
            "id": sid,
            "label": _node_label(table, record),
            "table": table,
            "tableLabel": _TABLE_LABELS.get(table, table),
            "props": {k: v for k, v in record.items() if k != "id"},
        }
    }


async def _query(surql: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{SURREAL_URL}/sql", content=surql, headers=_HEADERS)
        r.raise_for_status()
        return r.json()


def _ok(resp: list[dict], idx: int = 0) -> list[Any]:
    if idx >= len(resp):
        return []
    item = resp[idx]
    if item.get("status") != "OK":
        return []
    return item.get("result") or []

# ---- endpoints -----------------------------------------------------------

@app.get("/api/health")
async def health():
    try:
        await _query("RETURN 1;")
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/search")
async def search(q: str = Query(""), limit: int = 20):
    q = q.strip()
    if not q:
        return {"nodes": []}
    esc = q.replace("\\", "\\\\").replace('"', '\\"')
    surql = (
        f'SELECT id, EduOrgFullName, EduOrgShortName, EduOrgOGRN, EduOrgINN, StatusName, RegionName '
        f'FROM certificate '
        f'WHERE string::lowercase(EduOrgFullName ?? "") CONTAINS string::lowercase("{esc}") '
        f'   OR EduOrgOGRN = "{esc}" OR EduOrgINN = "{esc}" '
        f'LIMIT {limit};'
    )
    resp = await _query(surql)
    return {"nodes": [_to_cy_node(r) for r in _ok(resp)]}


@app.get("/api/expand")
async def expand(id: str = Query(...)):
    table, key = _id_to_parts(id)
    if table not in _OUTGOING:
        raise HTTPException(status_code=400, detail=f"Unknown table: {table}")

    node_id = _rec_id(table, key)
    outgoing = _OUTGOING[table]
    incoming = _INCOMING[table]

    stmts = [f"SELECT * FROM {node_id};"]
    for et in outgoing:
        stmts.append(f"SELECT * FROM {et} WHERE in = {node_id} FETCH out;")
    for et in incoming:
        stmts.append(f"SELECT * FROM {et} WHERE out = {node_id} FETCH in;")

    resp = await _query("\n".join(stmts))

    base = _ok(resp, 0)
    if not base:
        raise HTTPException(status_code=404, detail="Node not found")

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    main = _to_cy_node(base[0])
    nodes[main["data"]["id"]] = main

    idx = 1
    for et in outgoing:
        for edge in _ok(resp, idx):
            in_id = _extract_id(edge.get("in"))
            out_val = edge.get("out")
            out_id = _extract_id(out_val)
            eid = _extract_id(edge.get("id")) or f"{et}_{in_id}_{out_id}"
            if isinstance(out_val, dict):
                nb = _to_cy_node(out_val)
                nodes[nb["data"]["id"]] = nb
            if in_id and out_id:
                edges.append({"data": {"id": eid, "source": in_id, "target": out_id,
                                       "label": _EDGE_LABELS.get(et, et)}})
        idx += 1

    for et in incoming:
        for edge in _ok(resp, idx):
            in_val = edge.get("in")
            in_id = _extract_id(in_val)
            out_id = _extract_id(edge.get("out"))
            eid = _extract_id(edge.get("id")) or f"{et}_{in_id}_{out_id}"
            if isinstance(in_val, dict):
                nb = _to_cy_node(in_val)
                nodes[nb["data"]["id"]] = nb
            if in_id and out_id:
                edges.append({"data": {"id": eid, "source": in_id, "target": out_id,
                                       "label": _EDGE_LABELS.get(et, et)}})
        idx += 1

    return {"nodes": list(nodes.values()), "edges": edges}


@app.get("/api/regions")
async def regions():
    resp = await _query("SELECT VALUE name FROM region ORDER BY name;")
    return {"regions": _ok(resp)}


@app.get("/api/levels")
async def levels():
    resp = await _query("SELECT VALUE name FROM educational_level ORDER BY name;")
    return {"levels": _ok(resp)}
