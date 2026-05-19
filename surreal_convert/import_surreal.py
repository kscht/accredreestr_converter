"""JSONL → SurrealDB: быстрый импорт графа по specs/kg/mapping.json.

Транспорт: httpx async HTTP POST /sql (параллельные батчи).
С флагом ``--recreate`` использует CREATE вместо UPSERT (нет проверки существования,
заметно быстрее при полной пересборке базы).

Пример:
    python -m surreal_convert.import_surreal out/data.jsonl \\
        --url http://localhost:8000 --ns accred --db accred --recreate
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any, Iterator

import httpx

_ROOT = Path(__file__).resolve().parents[1]
_KG_DEFAULT = _ROOT / "specs" / "kg" / "mapping.json"

DEFAULT_URL = "http://localhost:8000"
DEFAULT_NS = "accred"
DEFAULT_DB = "accred"
DEFAULT_USER = "root"
DEFAULT_PASS = "root"
DEFAULT_BATCH = 500   # сертификатов на один HTTP-запрос
DEFAULT_WORKERS = 4   # параллельных HTTP-запросов

_NODE_TABLES = [
    "certificate",
    "supplement",
    "decision",
    "educational_program",
    "educational_level",
    "region",
    "actual_education_organization",
]
_EDGE_TABLES = [
    "has_supplement",
    "has_decision",
    "has_educational_program",
    "has_education_level",
    "offers_education_level",
    "in_region",
    "has_actual_education_organization",
]


def _to_http_url(url: str) -> str:
    """Принимает ws://, wss:// или http(s)://, возвращает http(s)://."""
    if url.startswith("ws://"):
        return "http://" + url[5:]
    if url.startswith("wss://"):
        return "https://" + url[6:]
    return url


def _rec_id(table: str, key: str) -> str:
    escaped = key.replace("\\", "\\\\").replace("`", "\\`")
    return f"{table}:`{escaped}`"


def _level_key(level_name: str) -> str:
    n = (level_name or "").strip()
    return hashlib.sha256(n.encode("utf-8")).hexdigest() if n else ""


def _region_key(region_name: str) -> str:
    n = (region_name or "").strip()
    return hashlib.sha256(n.encode("utf-8")).hexdigest() if n else ""


def _surql_val(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if isinstance(val, float) and (val != val or abs(val) == float("inf")):
            return None
        return str(val)
    if isinstance(val, str):
        return '"' + val.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(val, list):
        parts = [_surql_val(i) for i in val]
        return "[" + ", ".join(p for p in parts if p is not None) + "]"
    return None


def _scalar_props(obj: dict[str, Any], groups: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for g in groups:
        for k in g.get("json_keys") or []:
            if k in obj and obj[k] is not None:
                out[k] = obj[k]
    return out


def _set_clause(props: dict[str, Any]) -> str:
    parts = []
    for k, v in sorted(props.items()):
        sv = _surql_val(v)
        if sv is not None:
            parts.append(f"{k} = {sv}")
    return (" SET " + ", ".join(parts)) if parts else ""


def _upsert(rid: str, props: dict[str, Any]) -> str:
    return f"UPSERT {rid}{_set_clause(props)};"


def _create_stmt(rid: str, props: dict[str, Any]) -> str:
    """CREATE — быстрее UPSERT: нет проверки существования. Только при --recreate."""
    return f"CREATE {rid}{_set_clause(props)};"


def _relate(from_rid: str, edge: str, to_rid: str, edge_key: str) -> str:
    erid = _rec_id(edge, edge_key)
    return f"UPSERT {erid} SET in = {from_rid}, out = {to_rid};"


def _relate_create(from_rid: str, edge: str, to_rid: str, edge_key: str) -> str:
    erid = _rec_id(edge, edge_key)
    return f"CREATE {erid} SET in = {from_rid}, out = {to_rid};"


def load_kg_mapping(path: Path | None = None) -> dict[str, Any]:
    p = path or _KG_DEFAULT
    return json.loads(p.read_text(encoding="utf-8"))


def _kind_by_name(mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["kind"]: n for n in mapping["node_kinds"]}


def iter_surql_for_certificate(
    mapping: dict[str, Any],
    obj: dict[str, Any],
    use_create: bool = False,
) -> Iterator[str]:
    """Генерирует SurrealQL-операторы для одной записи JSONL (один сертификат).

    ``use_create=True`` использует CREATE вместо UPSERT (только при --recreate,
    когда база гарантированно пуста — нет проверки существования, быстрее).
    """
    node_fn  = _create_stmt if use_create else _upsert
    edge_fn  = _relate_create if use_create else _relate

    kinds = _kind_by_name(mapping)
    cid = obj.get("Id")
    if not cid:
        return
    cid_s = str(cid).strip()
    if not cid_s:
        return

    cert_rid = _rec_id("certificate", cid_s)
    cert_k = kinds["Certificate"]
    cert_props = _scalar_props(obj, cert_k.get("scalar_property_groups") or [])
    cert_props.pop("RegionName", None)
    cert_props["uri"] = f"urn:accred:v1:Certificate:{cid_s}"

    # Проекция _graph → быстрые поля для фильтрации во вьювере
    graph = obj.get("_graph") or {}
    g_org = graph.get("org") or {}
    if graph.get("region"):
        cert_props["g_region"] = graph["region"]
    if graph.get("region_short"):
        cert_props["g_region_short"] = graph["region_short"]
    if graph.get("control_organ"):
        cert_props["g_control_organ"] = graph["control_organ"]
    if graph.get("control_organ_short"):
        cert_props["g_control_organ_short"] = graph["control_organ_short"]
    if graph.get("edu_levels"):
        cert_props["g_edu_levels"] = graph["edu_levels"]
    if g_org.get("display_name"):
        cert_props["g_display_name"] = g_org["display_name"]
    if g_org.get("founder_key"):
        cert_props["g_founder_key"] = g_org["founder_key"]
    if g_org.get("founder_label"):
        cert_props["g_founder_label"] = g_org["founder_label"]

    yield node_fn(cert_rid, cert_props)

    rn = str(obj.get("RegionName") or "").strip()
    if rn:
        rkey = _region_key(rn)
        region_rid = _rec_id("region", rkey)
        yield node_fn(region_rid, {"name": rn, "uri": f"urn:accred:v1:Region:{rkey}"})
        yield edge_fn(cert_rid, "in_region", region_rid, f"cert_{cid_s}_{rkey}")

    levels_on_certificate: set[str] = set()

    for si, sup in enumerate(obj.get("Supplements") or []):
        if not isinstance(sup, dict):
            continue
        sid = sup.get("Id")
        if sid is None:
            continue
        sid_s = str(sid)
        sup_key = f"{cid_s}_{sid_s}"
        sup_rid = _rec_id("supplement", sup_key)
        sup_k = kinds["Supplement"]
        sup_props = _scalar_props(sup, sup_k.get("scalar_property_groups") or [])
        sup_props["uri"] = f"urn:accred:v1:Supplement:{cid_s}:{sid_s}"
        yield node_fn(sup_rid, sup_props)
        yield edge_fn(cert_rid, "has_supplement", sup_rid, sup_key)

        sup_level_names: set[str] = set()
        prog_k = kinds["EducationalProgram"]
        for slot, prog in enumerate(sup.get("EducationalPrograms") or []):
            if not isinstance(prog, dict):
                continue
            prog_id = str(prog.get("Id") or "")
            prog_key = f"{cid_s}_{sid_s}_{slot}_{prog_id}"
            prog_rid = _rec_id("educational_program", prog_key)
            prog_props = _scalar_props(prog, prog_k.get("scalar_property_groups") or [])
            prog_props.pop("EduLevelName", None)
            prog_props["uri"] = f"urn:accred:v1:EducationalProgram:{prog_key}"
            yield node_fn(prog_rid, prog_props)
            yield edge_fn(sup_rid, "has_educational_program", prog_rid, prog_key)

            level_name = str(prog.get("EduLevelName") or "").strip()
            if level_name:
                levels_on_certificate.add(level_name)
                sup_level_names.add(level_name)
                lkey = _level_key(level_name)
                level_rid = _rec_id("educational_level", lkey)
                yield node_fn(level_rid, {"name": level_name, "uri": f"urn:accred:v1:EducationalLevel:{lkey}"})
                yield edge_fn(prog_rid, "has_education_level", level_rid, f"{prog_key}_{lkey}")

        sub_aeo = sup.get("ActualEducationOrganization")
        if isinstance(sub_aeo, dict) and sub_aeo.get("Id") is not None:
            aeo_k = kinds["ActualEducationOrganization"]
            aeo_id = str(sub_aeo.get("Id"))
            aeo_key = f"{cid_s}_sup_{aeo_id}"
            aeo_rid = _rec_id("actual_education_organization", aeo_key)
            aeo_props = _scalar_props(sub_aeo, aeo_k.get("scalar_property_groups") or [])
            aeo_props.pop("RegionName", None)
            aeo_props["uri"] = f"urn:accred:v1:AEO:{cid_s}:supplement:{aeo_id}"
            yield node_fn(aeo_rid, aeo_props)
            yield edge_fn(sup_rid, "has_actual_education_organization", aeo_rid, f"{sup_key}_aeo")

            sub_rn = str(sub_aeo.get("RegionName") or "").strip()
            if sub_rn:
                rkey = _region_key(sub_rn)
                region_rid = _rec_id("region", rkey)
                yield node_fn(region_rid, {"name": sub_rn, "uri": f"urn:accred:v1:Region:{rkey}"})
                yield edge_fn(aeo_rid, "in_region", region_rid, f"{aeo_key}_{rkey}")

            for ln in sorted(sup_level_names):
                lkey = _level_key(ln)
                level_rid = _rec_id("educational_level", lkey)
                yield edge_fn(aeo_rid, "offers_education_level", level_rid, f"{aeo_key}_off_{lkey}")

    dec_k = kinds["Decision"]
    for di, dec in enumerate(obj.get("Decisions") or []):
        if not isinstance(dec, dict):
            continue
        did = dec.get("Id")
        if did is None or (isinstance(did, str) and not str(did).strip()):
            continue
        did_s = str(did).strip()
        dec_key = f"{cid_s}_{did_s}"
        dec_rid = _rec_id("decision", dec_key)
        dec_props = _scalar_props(dec, dec_k.get("scalar_property_groups") or [])
        dec_props["uri"] = f"urn:accred:v1:Decision:{cid_s}:{did_s}"
        yield node_fn(dec_rid, dec_props)
        yield edge_fn(cert_rid, "has_decision", dec_rid, dec_key)

    root_aeo = obj.get("ActualEducationOrganization")
    if isinstance(root_aeo, dict) and root_aeo.get("Id") is not None:
        aeo_k = kinds["ActualEducationOrganization"]
        aeo_id = str(root_aeo.get("Id"))
        aeo_key = f"{cid_s}_cert_{aeo_id}"
        aeo_rid = _rec_id("actual_education_organization", aeo_key)
        aeo_props = _scalar_props(root_aeo, aeo_k.get("scalar_property_groups") or [])
        aeo_props.pop("RegionName", None)
        aeo_props["uri"] = f"urn:accred:v1:AEO:{cid_s}:certificate:{aeo_id}"
        yield node_fn(aeo_rid, aeo_props)
        yield edge_fn(cert_rid, "has_actual_education_organization", aeo_rid, f"{cid_s}_cert_aeo")

        root_rn = str(root_aeo.get("RegionName") or "").strip()
        if root_rn:
            rkey = _region_key(root_rn)
            region_rid = _rec_id("region", rkey)
            yield node_fn(region_rid, {"name": root_rn, "uri": f"urn:accred:v1:Region:{rkey}"})
            yield edge_fn(aeo_rid, "in_region", region_rid, f"{aeo_key}_{rkey}")

        for ln in sorted(levels_on_certificate):
            lkey = _level_key(ln)
            level_rid = _rec_id("educational_level", lkey)
            yield edge_fn(aeo_rid, "offers_education_level", level_rid, f"{aeo_key}_off_{lkey}")


# ---------------------------------------------------------------------------
# HTTP async transport
# ---------------------------------------------------------------------------

async def _post_sql(client: httpx.AsyncClient, url: str, headers: dict, sql: str) -> None:
    r = await client.post(f"{url}/sql", content=sql.encode("utf-8"), headers=headers)
    r.raise_for_status()


async def _import_async(
    jsonl_path: Path,
    *,
    url: str,
    ns: str,
    db: str,
    user: str,
    password: str,
    batch_size: int,
    workers: int,
    limit: int | None,
    recreate: bool,
    mapping_path: Path | None,
) -> int:
    http_url = _to_http_url(url)
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    headers = {
        "Accept": "application/json",
        "Content-Type": "text/plain; charset=utf-8",
        "Authorization": f"Basic {auth}",
        "surreal-ns": ns,
        "surreal-db": db,
    }

    sem = asyncio.Semaphore(workers)

    async with httpx.AsyncClient(timeout=120.0) as client:
        if recreate:
            drop_sql = "\n".join(
                f"REMOVE TABLE IF EXISTS {t};" for t in _NODE_TABLES + _EDGE_TABLES
            )
            await _post_sql(client, http_url, headers, drop_sql)
            logging.info("Таблицы удалены (--recreate)")

        mapping = load_kg_mapping(mapping_path)
        use_create = recreate  # CREATE быстрее UPSERT при гарантированно пустой базе

        tasks: list[asyncio.Task] = []
        batch: list[str] = []
        processed = 0

        async def send(sql: str) -> None:
            async with sem:
                await _post_sql(client, http_url, headers, sql)

        def flush() -> None:
            nonlocal batch
            if not batch:
                return
            tasks.append(asyncio.create_task(send("\n".join(batch))))
            batch = []

        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    logging.warning("Пропуск строки (не JSON): %s", exc)
                    continue

                batch.extend(iter_surql_for_certificate(mapping, obj, use_create=use_create))
                processed += 1

                if processed % batch_size == 0:
                    flush()
                    logging.info("Запущено батчей: %d (сертификатов: %d)", len(tasks), processed)

                if limit is not None and processed >= limit:
                    break

        flush()
        await asyncio.gather(*tasks)

    logging.info("Всего импортировано: %d", processed)
    return processed


def import_surreal(
    jsonl_path: Path,
    *,
    url: str = DEFAULT_URL,
    ns: str = DEFAULT_NS,
    db: str = DEFAULT_DB,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    batch_size: int = DEFAULT_BATCH,
    workers: int = DEFAULT_WORKERS,
    limit: int | None = None,
    recreate: bool = False,
    mapping_path: Path | None = None,
) -> int:
    return asyncio.run(
        _import_async(
            jsonl_path,
            url=url,
            ns=ns,
            db=db,
            user=user,
            password=password,
            batch_size=batch_size,
            workers=workers,
            limit=limit,
            recreate=recreate,
            mapping_path=mapping_path,
        )
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Импорт JSONL (выход convert.py) в SurrealDB как граф по specs/kg/mapping.json. "
            "Транспорт: httpx async HTTP. С --recreate использует CREATE (быстрее UPSERT)."
        ),
    )
    p.add_argument("jsonl", type=Path, help="Путь к .jsonl")
    p.add_argument("--url", default=DEFAULT_URL,
                   help=f"URL SurrealDB — http(s):// или ws(s):// (по умолчанию {DEFAULT_URL})")
    p.add_argument("--ns",       default=DEFAULT_NS,   help=f"Namespace (по умолчанию {DEFAULT_NS})")
    p.add_argument("--db",       default=DEFAULT_DB,   help=f"Database (по умолчанию {DEFAULT_DB})")
    p.add_argument("--user",     default=DEFAULT_USER, help="Пользователь SurrealDB")
    p.add_argument("--password", default=DEFAULT_PASS, help="Пароль SurrealDB")
    p.add_argument("--batch", type=int, default=DEFAULT_BATCH, metavar="N",
                   help=f"Сертификатов на один HTTP-запрос (по умолчанию {DEFAULT_BATCH})")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS, metavar="N",
                   help=f"Параллельных HTTP-запросов (по умолчанию {DEFAULT_WORKERS})")
    p.add_argument("--limit",   type=int, default=None, metavar="N",
                   help="Не более N строк JSONL")
    p.add_argument("--recreate", action="store_true",
                   help="Удалить все таблицы перед импортом; использует CREATE вместо UPSERT")
    p.add_argument("--mapping",  type=Path, default=None,
                   help="Путь к specs/kg/mapping.json (по умолчанию из репозитория)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = _parse_args(argv)
    if not args.jsonl.is_file():
        logging.error("Файл не найден: %s", args.jsonl)
        return 2
    return import_surreal(
        args.jsonl.resolve(),
        url=args.url,
        ns=args.ns,
        db=args.db,
        user=args.user,
        password=args.password,
        batch_size=args.batch,
        workers=args.workers,
        limit=args.limit,
        recreate=args.recreate,
        mapping_path=args.mapping.resolve() if args.mapping else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
