"""JSONL → Cypher: MERGE узлов и рёбер по specs/kg/mapping.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterator

_ROOT = Path(__file__).resolve().parents[1]
_KG_DEFAULT = _ROOT / "specs" / "kg" / "mapping.json"

# Типы рёбер Neo4j (одинаковые имена для двух вариантов hasActualEducationOrganization)
_REL_TYPE: dict[str, str] = {
    "hasSupplement": "HAS_SUPPLEMENT",
    "hasDecision": "HAS_DECISION",
    "hasEducationalProgram": "HAS_EDUCATIONAL_PROGRAM",
    "hasActualEducationOrganization": "HAS_ACTUAL_EDUCATION_ORGANIZATION",
    "hasEducationLevel": "HAS_EDUCATION_LEVEL",
    "offersEducationLevel": "OFFERS_EDUCATION_LEVEL",
    "inRegion": "IN_REGION",
}


def _educational_level_uri(level_name: str) -> str:
    """Стабильный URI узла уровня образования по тексту EduLevelName (UTF-8)."""
    n = (level_name or "").strip()
    if not n:
        return ""
    h = hashlib.sha256(n.encode("utf-8")).hexdigest()
    return f"urn:accred:v1:EducationalLevel:{h}"


def _region_uri(region_name: str) -> str:
    """Стабильный URI узла региона по тексту RegionName (UTF-8)."""
    n = (region_name or "").strip()
    if not n:
        return ""
    h = hashlib.sha256(n.encode("utf-8")).hexdigest()
    return f"urn:accred:v1:Region:{h}"


def _iter_in_region(
    entity_var: str,
    raw_region: Any,
    region_name_to_var: dict[str, str],
    regions_merged: set[str],
) -> Iterator[str]:
    rn = str(raw_region).strip() if raw_region is not None else ""
    if not rn:
        return
    rv = region_name_to_var.setdefault(rn, f"rg{len(region_name_to_var)}")
    if rn not in regions_merged:
        regions_merged.add(rn)
        ruri = _region_uri(rn)
        yield f"MERGE ({rv}:Region {{uri: {_cypher_string(ruri)}}})"
        yield f"SET {rv}.name = {_cypher_string(rn)}"
    rt = _REL_TYPE["inRegion"]
    yield f"MERGE ({entity_var})-[:{rt}]->({rv})"


def load_kg_mapping(path: Path | None = None) -> dict[str, Any]:
    p = path or _KG_DEFAULT
    return json.loads(p.read_text(encoding="utf-8"))


def _subst(template: str, ctx: dict[str, Any]) -> str:
    out = template

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        v = ctx.get(key)
        if v is None:
            return ""
        return str(v)

    return re.sub(r"\{([^}]+)\}", repl, out)


def _cypher_string(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _cypher_literal(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if isinstance(val, float) and (val != val or val in (float("inf"), float("-inf"))):
            return None
        return str(val)
    if isinstance(val, str):
        return _cypher_string(val)
    return _cypher_string(json.dumps(val, ensure_ascii=False))


def _props_set_lines(var: str, props: dict[str, str]) -> list[str]:
    """Строки SET var.key = literal (без None)."""
    lines: list[str] = []
    for k, lit in sorted(props.items()):
        if lit is None:
            continue
        if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", k):
            lines.append(f"SET {var}.{k} = {lit}")
        else:
            lines.append(f"SET {var}[{_cypher_string(k)}] = {lit}")
    return lines


def _scalar_props(
    obj: dict[str, Any], groups: list[dict[str, Any]]
) -> dict[str, str]:
    out: dict[str, str] = {}
    for g in groups:
        for k in g.get("json_keys") or []:
            if k not in obj:
                continue
            lit = _cypher_literal(obj.get(k))
            if lit is not None:
                out[k] = lit
    return out


def _kind_by_name(mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["kind"]: n for n in mapping["node_kinds"]}


def iter_cypher_for_certificate(
    mapping: dict[str, Any], obj: dict[str, Any]
) -> Iterator[str]:
    """Строки Cypher для одной записи JSONL (один сертификат)."""
    kinds = _kind_by_name(mapping)
    cid = obj.get("Id")
    if cid is None:
        return
    cid_s = str(cid).strip()
    if not cid_s:
        return
    ctx0: dict[str, Any] = {
        "Id": cid_s,
        "certificate_Id": cid_s,
    }

    region_name_to_var: dict[str, str] = {}
    regions_merged: set[str] = set()

    cert = kinds["Certificate"]
    cert_uri = _subst(cert["id_template"], ctx0)
    yield f"MERGE (c:Certificate {{uri: {_cypher_string(cert_uri)}}})"
    cp = _scalar_props(obj, cert.get("scalar_property_groups") or [])
    cp.pop("RegionName", None)
    for line in _props_set_lines("c", cp):
        yield line
    yield from _iter_in_region(
        "c", obj.get("RegionName"), region_name_to_var, regions_merged
    )

    level_name_to_var: dict[str, str] = {}
    levels_merged: set[str] = set()
    levels_on_certificate: set[str] = set()

    # Supplements + HAS_SUPPLEMENT (уникальные имена переменных в одном запросе Cypher)
    for si, sup in enumerate(obj.get("Supplements") or []):
        if not isinstance(sup, dict):
            continue
        sid = sup.get("Id")
        if sid is None:
            continue
        sid_s = str(sid)
        vs = f"s{si}"
        sup_level_names: set[str] = set()
        ctx_s = {**ctx0, "Supplement.Id": sid_s}
        sup_k = kinds["Supplement"]
        sup_uri = _subst(sup_k["id_template"], ctx_s)
        yield f"MERGE ({vs}:Supplement {{uri: {_cypher_string(sup_uri)}}})"
        sp = _scalar_props(sup, sup_k.get("scalar_property_groups") or [])
        for line in _props_set_lines(vs, sp):
            yield line
        rt = _REL_TYPE["hasSupplement"]
        yield f"MERGE (c)-[:{rt}]->({vs})"

        # Programs + узлы уровня образования (EduLevelName)
        prog_k = kinds["EducationalProgram"]
        rt_el = _REL_TYPE["hasEducationLevel"]
        for slot, prog in enumerate(sup.get("EducationalPrograms") or []):
            if not isinstance(prog, dict):
                continue
            ctx_p = {
                **ctx0,
                "supplement_Id": sid_s,
                "program_slot": str(slot),
                "EducationalProgram.Id": prog.get("Id"),
            }
            prog_uri = _subst(prog_k["id_template"], ctx_p)
            vp = f"p_si{si}_{slot}"
            yield f"MERGE ({vp}:EducationalProgram {{uri: {_cypher_string(prog_uri)}}})"
            pp = _scalar_props(prog, prog_k.get("scalar_property_groups") or [])
            pp.pop("EduLevelName", None)
            for line in _props_set_lines(vp, pp):
                yield line
            rt_p = _REL_TYPE["hasEducationalProgram"]
            yield f"MERGE ({vs})-[:{rt_p}]->({vp})"

            raw_ln = prog.get("EduLevelName")
            level_name = str(raw_ln).strip() if raw_ln is not None else ""
            if level_name:
                levels_on_certificate.add(level_name)
                sup_level_names.add(level_name)
                el_uri = _educational_level_uri(level_name)
                vel = level_name_to_var.setdefault(
                    level_name, f"elv{len(level_name_to_var)}"
                )
                if level_name not in levels_merged:
                    levels_merged.add(level_name)
                    yield f"MERGE ({vel}:EducationalLevel {{uri: {_cypher_string(el_uri)}}})"
                    yield f"SET {vel}.name = {_cypher_string(level_name)}"
                yield f"MERGE ({vp})-[:{rt_el}]->({vel})"

        # AEO on supplement
        sub = sup.get("ActualEducationOrganization")
        if isinstance(sub, dict) and sub.get("Id") is not None:
            aeo_k = kinds["ActualEducationOrganization"]
            ctx_a = {
                **ctx0,
                "scope": "supplement",
                "AEO.Id": sub.get("Id"),
            }
            aeo_uri = _subst(aeo_k["id_template"], ctx_a)
            va = f"a_si{si}"
            yield f"MERGE ({va}:ActualEducationOrganization {{uri: {_cypher_string(aeo_uri)}}})"
            ap = _scalar_props(sub, aeo_k.get("scalar_property_groups") or [])
            ap.pop("RegionName", None)
            for line in _props_set_lines(va, ap):
                yield line
            yield from _iter_in_region(
                va, sub.get("RegionName"), region_name_to_var, regions_merged
            )
            rt_a = _REL_TYPE["hasActualEducationOrganization"]
            yield f"MERGE ({vs})-[:{rt_a}]->({va})"
            rt_offer = _REL_TYPE["offersEducationLevel"]
            for ln in sorted(sup_level_names):
                vel = level_name_to_var[ln]
                yield f"MERGE ({va})-[:{rt_offer}]->({vel})"

    # Decisions
    dec_k = kinds["Decision"]
    for di, dec in enumerate(obj.get("Decisions") or []):
        if not isinstance(dec, dict):
            continue
        did = dec.get("Id")
        if did is None or (isinstance(did, str) and not str(did).strip()):
            continue
        ctx_d = {**ctx0, "Decision.Id": str(did).strip()}
        dec_uri = _subst(dec_k["id_template"], ctx_d)
        vd = f"d{di}"
        yield f"MERGE ({vd}:Decision {{uri: {_cypher_string(dec_uri)}}})"
        dp = _scalar_props(dec, dec_k.get("scalar_property_groups") or [])
        for line in _props_set_lines(vd, dp):
            yield line
        rt_d = _REL_TYPE["hasDecision"]
        yield f"MERGE (c)-[:{rt_d}]->({vd})"

    # Root AEO
    root = obj.get("ActualEducationOrganization")
    if isinstance(root, dict) and root.get("Id") is not None:
        aeo_k = kinds["ActualEducationOrganization"]
        ctx_a = {**ctx0, "scope": "certificate", "AEO.Id": root.get("Id")}
        aeo_uri = _subst(aeo_k["id_template"], ctx_a)
        yield f"MERGE (a0:ActualEducationOrganization {{uri: {_cypher_string(aeo_uri)}}})"
        ap = _scalar_props(root, aeo_k.get("scalar_property_groups") or [])
        ap.pop("RegionName", None)
        for line in _props_set_lines("a0", ap):
            yield line
        yield from _iter_in_region(
            "a0", root.get("RegionName"), region_name_to_var, regions_merged
        )
        rt_a = _REL_TYPE["hasActualEducationOrganization"]
        yield f"MERGE (c)-[:{rt_a}]->(a0)"
        rt_offer = _REL_TYPE["offersEducationLevel"]
        for ln in sorted(levels_on_certificate):
            vel = level_name_to_var[ln]
            yield f"MERGE (a0)-[:{rt_offer}]->({vel})"


def export_jsonl_to_cypher(
    jsonl_path: Path,
    out_path: Path,
    *,
    mapping_path: Path | None,
    limit: int | None,
    semicolon_after_certificate: bool = False,
    clear_database_first: bool = False,
) -> int:
    mapping = load_kg_mapping(mapping_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    processed = 0
    with jsonl_path.open(encoding="utf-8") as inp, out_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as out:
        if clear_database_first:
            out.write(
                "// ВНИМАНИЕ: следующая команда удаляет все узлы и связи в активной базе Neo4j.\n"
            )
            out.write("MATCH (n) DETACH DELETE n;\n\n")
        out.write("// Generated from JSONL by cypher_convert.export_cypher\n")
        out.write("// Labels match specs/kg/mapping.json node_kinds.kind\n")
        if semicolon_after_certificate:
            out.write("// Each certificate block ends with ';' for multi-statement clients (Neo4j Browser).\n")
        out.write("\n")
        for line in inp:
            line = line.strip()
            if not line:
                continue
            processed += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                logging.warning("Пропуск строки (не JSON): %s", exc)
                if limit is not None and processed >= limit:
                    break
                continue
            out.write(f"// --- certificate line {processed} ---\n")
            stmts = list(iter_cypher_for_certificate(mapping, obj))
            for i, stmt in enumerate(stmts):
                if semicolon_after_certificate and i == len(stmts) - 1:
                    out.write(stmt + ";\n")
                else:
                    out.write(stmt + "\n")
            out.write("\n")
            if limit is not None and processed >= limit:
                break
    logging.info("Обработано непустых строк JSONL: %s", processed)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Экспорт JSONL (выход convert.py) в Cypher для Neo4j по specs/kg/mapping.json.",
    )
    p.add_argument("jsonl", type=Path, help="Путь к .jsonl")
    p.add_argument("-o", "--output", type=Path, required=True, help="Выходной .cypher")
    p.add_argument(
        "--mapping",
        type=Path,
        default=None,
        help="Путь к specs/kg/mapping.json (по умолчанию из репозитория)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Не более N непустых строк JSONL (как у sql_convert --limit)",
    )
    p.add_argument(
        "--semicolon",
        action="store_true",
        help="После каждого блока Cypher для одной строки JSONL ставить ';' (удобно для Neo4j Browser при запуске нескольких блоков подряд).",
    )
    p.add_argument(
        "--clear-graph",
        action="store_true",
        help="В начало файла добавить MATCH (n) DETACH DELETE n (полная очистка графа в Neo4j перед загрузкой).",
    )
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
    return export_jsonl_to_cypher(
        args.jsonl.resolve(),
        args.output.resolve(),
        mapping_path=args.mapping.resolve() if args.mapping else None,
        limit=args.limit,
        semicolon_after_certificate=args.semicolon,
        clear_database_first=args.clear_graph,
    )


if __name__ == "__main__":
    raise SystemExit(main())
