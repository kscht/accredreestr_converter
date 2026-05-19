#!/usr/bin/env python3
"""Черновик словаря наименований организаций через OpenRouter (LLM), **вне** конвертера.

Читает уникальные строки из JSONL (шесть полей имён, см. ``iter_organization_name_fields`` в ``org_name_normalize``)
или из текстового файла (одна строка = одно имя). Отправляет батчи в Chat Completions API,
ожидает ответ строго в JSON — массив объектов ``raw``, ``suggested_display``, опционально
``reason_short``.

Запросы к API выполняются через **asyncio** + **httpx**. По умолчанию **50** параллельных запросов
(``--concurrency``) и **адаптивный backoff**: при 429/5xx/сетевых сбоях снижается параллелизм и растёт пауза
между «окнами» запросов (см. ``--no-adaptive-backoff``).

В JSON каждая запись: ``raw`` и ``by_model`` — словарь **идентификаторов модели OpenRouter** →
``{ "suggested_display", "reason_short"? }``. При ``--merge-output`` с тем же ``-o`` добавляется/обновляется
ответ **текущей** ``--model`` в ``by_model``, не затирая другие модели.

Две модели в **одном** файле (одинаковая выборка имён → сравнение ``by_model`` без двух JSON)::

    python tools/draft_org_name_dictionary_openrouter.py \\
        --from-jsonl out/live.jsonl --name-kind all --full-unique-sample 2000 --random-seed 42 \\
        --model openai/gpt-4o-mini --second-model deepseek/deepseek-v4-flash \\
        -o out/org_name_dictionary_draft_openrouter.json

Токен: переменная окружения ``OPENROUTER_API_KEY`` (в репозиторий не класть).

Пример::

    cp .env.example .env   # вписать ключ в .env (файл в .gitignore)
    python tools/draft_org_name_dictionary_openrouter.py \\
        --from-jsonl out/live.jsonl --name-kind full --full-unique-sample 300 --random-seed 42 \\
        --concurrency 50 -o out/org_name_dict_full.json

    python tools/draft_org_name_dictionary_openrouter.py \\
        --from-jsonl out/live.jsonl --name-kind short --full-unique-sample 300 --random-seed 42 \\
        --merge-output -o out/org_name_dictionary_draft_openrouter.json

    # Ранние уникальные по порядку файла (смещение к началу снимка):
    python tools/draft_org_name_dictionary_openrouter.py --from-jsonl out/live.jsonl --name-kind all --limit 200 -o out/org_name_dict_draft.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any, Final, Literal

import httpx

NameKind = Literal["all", "full", "short"]

_FULL_NAME_FIELD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "Certificate.EduOrgFullName",
        "root_ActualEducationOrganization.FullName",
        "supplement_ActualEducationOrganization.FullName",
    }
)
_SHORT_NAME_FIELD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "Certificate.EduOrgShortName",
        "root_ActualEducationOrganization.ShortName",
        "supplement_ActualEducationOrganization.ShortName",
    }
)

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.org_name_normalize import (  # noqa: E402
    iter_organization_name_fields,
    mask_organization_name_enumeration_numbers_v1,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class BatchFetchResult:
    __slots__ = ("batch_index", "rows", "error", "saw_429", "saw_5xx", "saw_network")

    def __init__(
        self,
        batch_index: int,
        rows: list[dict[str, Any]] | None = None,
        error: str | None = None,
        *,
        saw_429: bool = False,
        saw_5xx: bool = False,
        saw_network: bool = False,
    ) -> None:
        self.batch_index = batch_index
        self.rows = rows
        self.error = error
        self.saw_429 = saw_429
        self.saw_5xx = saw_5xx
        self.saw_network = saw_network


def _load_root_dotenv_if_present() -> None:
    """Подхватить ``.env`` из корня репозитория (не перекрывает уже выставленные переменные)."""
    path = _ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key and key not in os.environ:
            os.environ[key] = val


_JSON_ANSWER_SHAPE = """Ответ **только** одним JSON-массивом объектов, без Markdown и без пояснений до или после:
[
  {"raw": "<точно как во входе>", "suggested_display": "...", "reason_short": "кратко опционально"}
]
Число объектов должно совпадать с числом строк во входном массиве; поле raw — дословно из входа."""

_SYSTEM_PROMPT_MIXED = """Ты помощник для подготовки словаря нормализации наименований образовательных организаций РФ (публичный реестр госаккредитации).
На вход даётся JSON-массив строк — **смесь** полных и кратких наименований из выгрузки (часто КАПС, кавычки ASCII). Это **одна** строка; по контексту строки сам оценивай, ближе ли она к **полному** или **краткому** имени, и не подменяй одно другим.

Задача: для каждой строки предложить **читаемое отображаемое** наименование на русском:
- уважай структуру ОПФ + «собственное имя» в кавычках + хвост (филиал и т.д.), если они есть;
- **не превращай** расписанное словами наименование (например «федеральное государственное бюджетное … учреждение») в сокращённую аббревиатуру (ФГБОУ, ФГБУН, ГАОУ и т.п.), если такой аббревиатуры **нет во входной строке** или она не является очевидным дословным фрагментом входа; иначе это подмена полного имени «кратким»;
- если во входе уже есть аббревиатура ОПФ — сохраняй её и только поправь регистр/пробелы по смыслу; аббревиатуры вроде ФГБОУ ВО, НИУ, МГУ, СОШ не разворачивай в длинный текст без необходимости;
- если во **входной** строке **одна и та же организация** названа **несколько раз** (через запятую, «также известна как», дубли полного и краткого варианта и т.п.), в `suggested_display` оставь **одно** наиболее уместное **единое** отображаемое наименование (обычно одно удачное сокращение или один согласованный вариант без повторов цепочки);
- не выдумывай другую организацию и не меняй смысл (только регистр, пробелы вокруг №, типографика кавычек не твоя забота — только текст);
- для длинных КАПС-простынь — заголовочный стиль по-русски (не ВСЕ ЗАГЛАВНЫЕ), служебные предлоги в середине строчные где уместно.

""" + _JSON_ANSWER_SHAPE

_SYSTEM_PROMPT_FULL_NAMES = """Ты помощник для подготовки словаря нормализации **полных** наименований образовательных организаций РФ (поля вроде ``EduOrgFullName``, ``FullName`` в карточке организации).
На вход даётся JSON-массив строк — каждая строка это **полное** (развёрнутое) наименование из реестра.

Задача: для каждой строки предложить **читаемое полное** отображаемое наименование на русском:
- уважай структуру ОПФ + имя собственной части в кавычках + хвост (филиал, муниципалитет и т.д.), если они есть;
- **не превращай** расписанное словами наименование в сокращённую аббревиатуру (ФГБОУ, ФГБУН, ГАОУ, МБОУ и т.п.), если такой аббревиатуры **нет во входной строке**;
- если во входе уже есть аббревиатура — сохраняй её и только поправь регистр/пробелы; не разворачивай аббревиатуру в длинный текст без необходимости;
- если во **входной** строке **одна и та же организация** названа **несколько раз** (через запятую, варианты написания и т.п.), в `suggested_display` оставь **одно** наиболее уместное **полное** единое наименование без дублирующей цепочки;
- не выдумывай другую организацию и не меняй смысл (только регистр, пробелы вокруг №; типографика кавычек не твоя забота);
- для длинных КАПС-простынь — заголовочный стиль по-русски (не ВСЕ ЗАГЛАВНЫЕ), служебные предлоги в середине строчные где уместно.

""" + _JSON_ANSWER_SHAPE

_SYSTEM_PROMPT_SHORT_NAMES = """Ты помощник для подготовки словаря нормализации **кратких** наименований образовательных организаций РФ (поля вроде ``EduOrgShortName``, ``ShortName`` в карточке организации).
На вход даётся JSON-массив строк — каждая строка это **краткое** наименование из реестра (часто аббревиатуры МБОУ, ГАОУ, СОШ и т.п.).

Задача: для каждой строки предложить **читаемое краткое** отображаемое наименование на русском:
- **не подменяй** краткое на **полное** юридическое наименование: не пиши «муниципальное бюджетное общеобразовательное учреждение …», если во входе такого текста **не было** (типичная ошибка — «развернуть» МБОУ в полную форму — этого делать нельзя);
- не разворачивай аббревиатуры МБОУ, ГБОУ, СПО, СОШ, ГАОУ и т.п. в длинные словесные формы, если во входе уже уместное краткое написание;
- если во **входной** строке **одна и та же организация** названа **несколько раз** (через запятую, дубли вариантов краткого имени и т.п.), в `suggested_display` оставь **одно** наиболее уместное **краткое** наименование без повторов цепочки;
- не выдумывай другую организацию и не меняй смысл (только регистр, пробелы вокруг №; типографика кавычек не твоя забота);
- для КАПС — приведи к обычному соглашению по регистру для аббревиатур и коротких имён, не превращай всю строку в «все заглавные», если это не принято для данного типа строки.

""" + _JSON_ANSWER_SHAPE


def system_prompt_for_name_kind(name_kind: NameKind) -> str:
    if name_kind == "full":
        return _SYSTEM_PROMPT_FULL_NAMES
    if name_kind == "short":
        return _SYSTEM_PROMPT_SHORT_NAMES
    return _SYSTEM_PROMPT_MIXED


def field_key_matches_name_kind(field_key: str, name_kind: NameKind) -> bool:
    if name_kind == "all":
        return True
    if name_kind == "full":
        return field_key in _FULL_NAME_FIELD_KEYS
    if name_kind == "short":
        return field_key in _SHORT_NAME_FIELD_KEYS
    raise ValueError(f"неизвестный name_kind: {name_kind!r}")


def _extract_json_value(text: str) -> Any:
    """Достаёт первый JSON-массив или объект из ответа модели (в т.ч. обёрнутый в ```json)."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t, re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = t.find(open_ch)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(t)):
            if t[i] == open_ch:
                depth += 1
            elif t[i] == close_ch:
                depth -= 1
                if depth == 0:
                    return json.loads(t[start : i + 1])
    raise ValueError("В ответе модели не найден распарсиваемый JSON")


def collect_unique_from_jsonl(path: Path, *, limit: int | None, name_kind: NameKind = "all") -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            for fk, val in iter_organization_name_fields(row):
                if not field_key_matches_name_kind(fk, name_kind):
                    continue
                s = val.strip()
                if s not in seen:
                    seen.add(s)
                    out.append(s)
                    if limit is not None and len(out) >= limit:
                        return out
    return out


def collect_all_unique_from_jsonl(path: Path, *, name_kind: NameKind = "all") -> list[str]:
    """Все уникальные непустые имена из выбранных полей за один проход по JSONL (отсортировано для стабильности)."""
    seen: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            for fk, val in iter_organization_name_fields(row):
                if not field_key_matches_name_kind(fk, name_kind):
                    continue
                s = val.strip()
                if s:
                    seen.add(s)
    return sorted(seen)


def collect_all_unique_from_lines(path: Path) -> list[str]:
    seen: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                seen.add(s)
    return sorted(seen)


def uniform_sample_strings(population_sorted: list[str], n: int, *, random_seed: int) -> list[str]:
    """Равномерная выборка без повторов; если ``n`` ≥ размера популяции — вся популяция."""
    if n <= 0:
        return []
    if len(population_sorted) <= n:
        return list(population_sorted)
    rng = random.Random(random_seed)
    return rng.sample(population_sorted, n)


def collect_unique_from_lines(path: Path, *, limit: int | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
            if limit is not None and len(out) >= limit:
                break
    return out


def _openrouter_headers(api_key: str) -> dict[str, str]:
    h: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    ref = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
    if ref:
        h["HTTP-Referer"] = ref
    title = os.environ.get("OPENROUTER_APP_TITLE", "accredreestr_converter").strip()
    if title:
        h["X-Title"] = title[:256]
    return h


def build_rows_from_batch_response(
    parsed: Any,
    api_batch: list[str],
    originals_batch: list[str],
    *,
    mask_enumeration_numbers: bool,
    batch_index: int,
    n_batches: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(parsed, list):
        return rows
    if len(parsed) != len(api_batch):
        print(
            f"Батч {batch_index + 1}/{n_batches}: длина ответа {len(parsed)} ≠ отправлено {len(api_batch)}; подбираю по полю raw.",
            file=sys.stderr,
        )
    by_raw = {
        str(it.get("raw", "")): it
        for it in parsed
        if isinstance(it, dict) and isinstance(it.get("raw"), str)
    }
    for idx, sent in enumerate(api_batch):
        orig = originals_batch[idx] if idx < len(originals_batch) else sent
        item = by_raw.get(sent) if sent in by_raw else (parsed[idx] if idx < len(parsed) else None)
        if not isinstance(item, dict) or not isinstance(item.get("raw"), str):
            continue
        if not isinstance(item.get("suggested_display"), str):
            continue
        row: dict[str, Any] = {
            "raw": item["raw"],
            "suggested_display": item["suggested_display"],
        }
        if isinstance(item.get("reason_short"), str):
            row["reason_short"] = item["reason_short"]
        if mask_enumeration_numbers and orig != sent:
            row["original_raw"] = orig
        rows.append(row)
    return rows


async def call_openrouter_async(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float,
    max_retries: int,
) -> str:
    body: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    headers = _openrouter_headers(api_key)
    last_err: BaseException | None = None
    for attempt in range(max(1, max_retries)):
        try:
            r = await client.post(OPENROUTER_URL, headers=headers, json=body)
            if r.status_code in (429, 502, 503, 504) and attempt + 1 < max_retries:
                await asyncio.sleep(min(90.0, 5.0 * (2**attempt)))
                continue
            # После исчерпания повторов 429/5xx — raise_for_status для явного HTTPStatusError
            r.raise_for_status()
            data = r.json()
            try:
                return str(data["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError) as e:
                raise RuntimeError(f"Неожиданный ответ API: {data!r}") from e
        except (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.RemoteProtocolError,
            httpx.PoolTimeout,
        ) as e:
            last_err = e
            if attempt + 1 >= max_retries:
                break
            await asyncio.sleep(min(60.0, 3.0 * (2**attempt)))
    assert last_err is not None
    raise last_err


async def _fetch_one_batch(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore | None,
    batch_index: int,
    originals_batch: list[str],
    api_batch: list[str],
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    temperature: float,
    max_retries: int,
    per_batch_sleep: float,
    mask_enumeration_numbers: bool,
    n_batches: int,
) -> BatchFetchResult:
    user_payload = json.dumps(api_batch, ensure_ascii=False)

    async def _inner() -> BatchFetchResult:
        try:
            content = await call_openrouter_async(
                client,
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                user_content=user_payload,
                temperature=temperature,
                max_retries=max_retries,
            )
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            res = BatchFetchResult(
                batch_index,
                None,
                f"HTTP {code}: {e!s}",
                saw_429=(code == 429),
                saw_5xx=(500 <= code < 600),
            )
            return res
        except (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.RemoteProtocolError,
            httpx.PoolTimeout,
        ) as e:
            return BatchFetchResult(batch_index, None, f"{type(e).__name__}: {e}", saw_network=True)
        except BaseException as e:
            return BatchFetchResult(batch_index, None, f"{type(e).__name__}: {e}")
        try:
            parsed = _extract_json_value(content)
        except (json.JSONDecodeError, ValueError) as e:
            return BatchFetchResult(
                batch_index,
                None,
                f"JSON: {e}\n---\n{content[:2000]}\n---",
            )
        if not isinstance(parsed, list):
            return BatchFetchResult(batch_index, None, f"ожидался массив, получено {type(parsed)}")
        rows = build_rows_from_batch_response(
            parsed,
            api_batch,
            originals_batch,
            mask_enumeration_numbers=mask_enumeration_numbers,
            batch_index=batch_index,
            n_batches=n_batches,
        )
        return BatchFetchResult(batch_index, rows, None)

    if semaphore is not None:
        async with semaphore:
            out = await _inner()
    else:
        out = await _inner()
    if per_batch_sleep > 0:
        await asyncio.sleep(float(per_batch_sleep))
    return out


async def run_all_batches_async(
    batches: list[list[str]],
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    temperature: float,
    read_timeout_s: int,
    max_retries: int,
    concurrency: int,
    sleep_after: float,
    mask_enumeration_numbers: bool,
    adaptive_backoff: bool,
    adaptive_min_concurrency: int,
    adaptive_max_gap_s: float,
) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    """Параллельные POST; при ``adaptive_backoff`` — окнами с подстройкой concurrency и паузы."""
    timeout = httpx.Timeout(
        connect=30.0,
        read=float(max(60, read_timeout_s)),
        write=60.0,
        pool=60.0,
    )
    pool_cap = max(64, int(concurrency) + 24)
    limits = httpx.Limits(max_keepalive_connections=pool_cap, max_connections=pool_cap)
    work: list[tuple[int, list[str], list[str]]] = []
    for bi, batch in enumerate(batches):
        originals_batch = list(batch)
        api_batch = (
            [mask_organization_name_enumeration_numbers_v1(x) for x in batch]
            if mask_enumeration_numbers
            else list(batch)
        )
        work.append((bi, originals_batch, api_batch))

    n_batches = len(batches)
    errors: list[tuple[int, str]] = []
    all_rows: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=timeout, limits=limits, http2=False) as client:
        if not adaptive_backoff:
            sem = asyncio.Semaphore(max(1, concurrency))
            tasks = [
                _fetch_one_batch(
                    client,
                    sem,
                    bi,
                    ob,
                    ab,
                    api_key=api_key,
                    model=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_retries=max_retries,
                    per_batch_sleep=sleep_after,
                    mask_enumeration_numbers=mask_enumeration_numbers,
                    n_batches=n_batches,
                )
                for bi, ob, ab in work
            ]
            outcomes = await asyncio.gather(*tasks)
            for res in sorted(outcomes, key=lambda x: x.batch_index):
                if res.error is not None:
                    errors.append((res.batch_index, res.error))
                    print(f"Батч {res.batch_index + 1}/{n_batches}: {res.error}", file=sys.stderr)
                elif res.rows is not None:
                    all_rows.extend(res.rows)
            return all_rows, errors

        current_c = max(1, int(concurrency))
        min_c = max(1, int(adaptive_min_concurrency))
        gap = max(0.0, float(sleep_after))
        window_i = 0
        pos = 0
        while pos < len(work):
            window_i += 1
            take = min(current_c, len(work) - pos)
            chunk = work[pos : pos + take]
            pos += take
            tasks = [
                _fetch_one_batch(
                    client,
                    None,
                    bi,
                    ob,
                    ab,
                    api_key=api_key,
                    model=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_retries=max_retries,
                    per_batch_sleep=0.0,
                    mask_enumeration_numbers=mask_enumeration_numbers,
                    n_batches=n_batches,
                )
                for bi, ob, ab in chunk
            ]
            outcomes = await asyncio.gather(*tasks)
            any_429 = any(r.saw_429 for r in outcomes)
            any_5xx = any(r.saw_5xx for r in outcomes)
            any_net = any(r.saw_network for r in outcomes)
            any_err = any(r.error is not None for r in outcomes)
            for res in sorted(outcomes, key=lambda x: x.batch_index):
                if res.error is not None:
                    errors.append((res.batch_index, res.error))
                    print(f"Батч {res.batch_index + 1}/{n_batches}: {res.error}", file=sys.stderr)
                elif res.rows is not None:
                    all_rows.extend(res.rows)
            if any_429:
                old_c, old_g = current_c, gap
                current_c = max(min_c, current_c // 2)
                gap = min(float(adaptive_max_gap_s), gap * 1.5 if gap > 0 else 0.75)
                print(
                    f"Адаптив: 429 в окне {window_i} → concurrency {old_c}→{current_c}, "
                    f"пауза между окнами {old_g:.3f}s→{gap:.3f}s",
                    file=sys.stderr,
                )
            elif any_5xx:
                old_c, old_g = current_c, gap
                current_c = max(min_c, current_c - max(1, current_c // 8))
                gap = min(float(adaptive_max_gap_s), gap * 1.25 if gap > 0 else 0.5)
                print(
                    f"Адаптив: 5xx в окне {window_i} → concurrency {old_c}→{current_c}, "
                    f"пауза {old_g:.3f}s→{gap:.3f}s",
                    file=sys.stderr,
                )
            elif any_net and any_err:
                old_g = gap
                gap = min(float(adaptive_max_gap_s), gap * 1.2 if gap > 0 else 0.4)
                print(
                    f"Адаптив: сеть в окне {window_i} → пауза {old_g:.3f}s→{gap:.3f}s (concurrency={current_c})",
                    file=sys.stderr,
                )
            if pos < len(work) and gap > 0:
                await asyncio.sleep(gap)
    return all_rows, errors


DICTIONARY_DRAFT_FORMAT_VERSION: Final[int] = 2


def normalize_dictionary_entry(
    entry: dict[str, Any],
    *,
    legacy_flat_model: str | None,
) -> dict[str, Any]:
    """Привести запись к виду ``{ raw, by_model?, original_raw? }`` (без устаревших полей верхнего уровня)."""
    raw = entry.get("raw")
    if not isinstance(raw, str):
        raw = ""
    out: dict[str, Any] = {"raw": raw}
    if isinstance(entry.get("original_raw"), str):
        out["original_raw"] = entry["original_raw"]

    by_model_in: Any = entry.get("by_model")
    bm: dict[str, dict[str, str]] = {}
    if isinstance(by_model_in, dict):
        for mk, mv in by_model_in.items():
            if not isinstance(mk, str) or not isinstance(mv, dict):
                continue
            chunk: dict[str, str] = {}
            if isinstance(mv.get("suggested_display"), str):
                chunk["suggested_display"] = mv["suggested_display"]
            rs = mv.get("reason_short")
            if isinstance(rs, str) and rs.strip():
                chunk["reason_short"] = rs
            if chunk:
                bm[mk] = chunk

    if legacy_flat_model and isinstance(entry.get("suggested_display"), str):
        if legacy_flat_model not in bm:
            chunk = {"suggested_display": entry["suggested_display"]}
            rs0 = entry.get("reason_short")
            if isinstance(rs0, str) and rs0.strip():
                chunk["reason_short"] = rs0
            bm[legacy_flat_model] = chunk

    if bm:
        out["by_model"] = bm
    return out


def entry_to_model_slice(entry_row: dict[str, Any], model_id: str) -> dict[str, Any]:
    """Обернуть плоский ответ API (raw, suggested_display, …) в запись с ``by_model``."""
    chunk: dict[str, str] = {"suggested_display": entry_row["suggested_display"]}
    if isinstance(entry_row.get("reason_short"), str) and entry_row["reason_short"].strip():
        chunk["reason_short"] = entry_row["reason_short"]
    out: dict[str, Any] = {"raw": entry_row["raw"], "by_model": {model_id: chunk}}
    if isinstance(entry_row.get("original_raw"), str):
        out["original_raw"] = entry_row["original_raw"]
    return out


def merge_entries(
    existing: list[dict[str, Any]],
    new_batch: list[dict[str, Any]],
    *,
    key_raw_casefold: bool,
    legacy_flat_model_for_existing: str | None,
    new_batch_model: str,
) -> list[dict[str, Any]]:
    def key(e: dict[str, Any]) -> str:
        r = e.get("raw", "")
        if not isinstance(r, str):
            return ""
        return r.casefold() if key_raw_casefold else r

    by_k: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for e in existing:
        ne = normalize_dictionary_entry(e, legacy_flat_model=legacy_flat_model_for_existing)
        k = key(ne)
        if k and k not in by_k:
            by_k[k] = ne
            order.append(k)
    for e in new_batch:
        ne = entry_to_model_slice(e, new_batch_model)
        k = key(ne)
        if not k:
            continue
        if k not in by_k:
            by_k[k] = ne
            order.append(k)
        else:
            cur = by_k[k]
            prev_bm: dict[str, Any] = dict(cur.get("by_model") or {})
            add_bm: dict[str, Any] = dict(ne.get("by_model") or {})
            merged_bm = {**prev_bm, **add_bm}
            merged_entry = {**cur, "by_model": merged_bm}
            if "original_raw" not in merged_entry and isinstance(ne.get("original_raw"), str):
                merged_entry["original_raw"] = ne["original_raw"]
            by_k[k] = merged_entry
    return [by_k[k] for k in order]


def collect_raw_casefolds_already_having_model(
    existing: list[dict[str, Any]],
    model_id: str,
    *,
    legacy_flat_model: str | None,
    mask_enumeration_numbers: bool,
) -> set[str]:
    """Для ``--merge-output``: пропускать raw, у которых уже есть ответ этой ``model_id``."""
    out: set[str] = set()
    for e in existing:
        ne = normalize_dictionary_entry(e, legacy_flat_model=legacy_flat_model)
        bm = ne.get("by_model")
        if not isinstance(bm, dict) or model_id not in bm:
            continue
        slot = bm[model_id]
        if not isinstance(slot, dict) or not isinstance(slot.get("suggested_display"), str):
            continue
        r = ne.get("raw")
        if not isinstance(r, str):
            continue
        key_raw = mask_organization_name_enumeration_numbers_v1(r) if mask_enumeration_numbers else r
        out.add(key_raw.casefold())
    return out


def raws_missing_model_slot(
    entries: list[dict[str, Any]],
    model_id: str,
    *,
    legacy_flat_model: str | None,
) -> list[str]:
    """Список ``raw``, для которых в ``by_model`` ещё нет валидного ``suggested_display`` у ``model_id``."""
    out: list[str] = []
    for e in entries:
        ne = normalize_dictionary_entry(e, legacy_flat_model=legacy_flat_model)
        r = ne.get("raw")
        if not isinstance(r, str) or not r.strip():
            continue
        bm = ne.get("by_model") or {}
        slot = bm.get(model_id)
        if isinstance(slot, dict) and isinstance(slot.get("suggested_display"), str):
            continue
        out.append(r)
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description="Черновик словаря имён организаций через OpenRouter (asyncio+httpx).",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-jsonl", type=Path, help="JSONL convert.py — собрать уникальные имена из шести полей")
    src.add_argument("--from-lines", type=Path, help="Текст UTF-8: одно наименование на строку")
    p.add_argument("-o", "--output", type=Path, default=_ROOT / "out" / "org_name_dictionary_draft_openrouter.json")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Максимум уникальных строк при линейном чтении (первые N уникальных по порядку сертификатов; не сочетать с --full-unique-sample)",
    )
    p.add_argument(
        "--full-unique-sample",
        type=int,
        metavar="N",
        default=None,
        help="Сначала собрать все уникальные имена по всему JSONL/файлу строк, затем равномерно выбрать N (воспроизводимо через --random-seed)",
    )
    p.add_argument("--random-seed", type=int, default=42, help="Seed для --full-unique-sample")
    p.add_argument("--batch-size", type=int, default=20, help="Сколько имён в одном запросе")
    p.add_argument(
        "--concurrency",
        type=int,
        default=50,
        help="Стартовый максимум параллельных HTTP-запросов; при --adaptive-backoff может снижаться",
    )
    p.add_argument("--model", type=str, default="openai/gpt-4o-mini", help="Идентификатор модели на OpenRouter")
    p.add_argument(
        "--second-model",
        type=str,
        default=None,
        metavar="ID",
        help="После --model: те же имена отправить второй модели (слияние в by_model; сравнение в одном файле)",
    )
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--timeout", type=int, default=300, help="Таймаут чтения ответа (сек); соединение до 30 с")
    p.add_argument(
        "--max-retries",
        type=int,
        default=6,
        help="Повторы при обрыве соединения / 429 / 5xx (на один батч)",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=0.35,
        help="Базовая пауза (с): при адаптивном режиме — между окнами батчей; без него — после каждого батча (внутри семафора)",
    )
    p.add_argument(
        "--adaptive-backoff",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Окнами: при 429/5xx/сети снижать concurrency и увеличивать паузу (по умолчанию включено)",
    )
    p.add_argument(
        "--adaptive-min-concurrency",
        type=int,
        default=5,
        help="Нижняя граница параллелизма при адаптивном backoff",
    )
    p.add_argument(
        "--adaptive-max-gap-s",
        type=float,
        default=45.0,
        help="Верхняя граница паузы между окнами (сек) при росте backoff",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Не вызывать API: показать первый user-payload и выйти",
    )
    p.add_argument(
        "--merge-output",
        action="store_true",
        help="Дописать в -o: для каждого raw добавить/обновить ветку by_model[--model]",
    )
    p.add_argument(
        "--mask-enumeration-numbers",
        action="store_true",
        help="Перед API: «№ 12» → «№ ⟨N⟩» (см. mask_organization_name_enumeration_numbers_v1); в JSON добавляется original_raw",
    )
    p.add_argument(
        "--name-kind",
        type=str,
        choices=("all", "full", "short"),
        default="all",
        help="Промпт и (при --from-jsonl) отбор полей: all — все шесть полей + смешанный промпт; full — EduOrgFullName и FullName; short — EduOrgShortName и ShortName. При --from-lines влияет только на выбор промпта.",
    )
    args = p.parse_args()

    _load_root_dotenv_if_present()

    if args.full_unique_sample is not None and args.limit is not None:
        print("Укажите либо --limit (ранние уникальные), либо --full-unique-sample N, не оба.", file=sys.stderr)
        return 2
    if args.full_unique_sample is not None and args.full_unique_sample < 1:
        print("--full-unique-sample N: N должен быть ≥ 1.", file=sys.stderr)
        return 2
    if args.concurrency < 1:
        print("--concurrency должен быть ≥ 1.", file=sys.stderr)
        return 2

    second_model = (args.second_model or "").strip() or None
    if second_model and second_model == args.model.strip():
        print("--second-model должен отличаться от --model.", file=sys.stderr)
        return 2

    name_kind: NameKind = args.name_kind  # type: ignore[assignment]
    system_prompt = system_prompt_for_name_kind(name_kind)

    population_unique: int | None = None
    if args.from_jsonl:
        if not args.from_jsonl.is_file():
            print(f"Нет файла: {args.from_jsonl}", file=sys.stderr)
            return 2
        if args.full_unique_sample is not None:
            all_u = collect_all_unique_from_jsonl(args.from_jsonl, name_kind=name_kind)
            population_unique = len(all_u)
            names = uniform_sample_strings(all_u, args.full_unique_sample, random_seed=args.random_seed)
            print(
                f"Уникальных по всему JSONL (name_kind={name_kind}): {population_unique}; "
                f"в равномерной выборке: {len(names)} (seed={args.random_seed}).",
                file=sys.stderr,
            )
        else:
            names = collect_unique_from_jsonl(args.from_jsonl, limit=args.limit, name_kind=name_kind)
    else:
        assert args.from_lines is not None
        if not args.from_lines.is_file():
            print(f"Нет файла: {args.from_lines}", file=sys.stderr)
            return 2
        if args.full_unique_sample is not None:
            all_u = collect_all_unique_from_lines(args.from_lines)
            population_unique = len(all_u)
            names = uniform_sample_strings(all_u, args.full_unique_sample, random_seed=args.random_seed)
            print(
                f"Уникальных по всему файлу строк: {population_unique}; в выборке: {len(names)} (seed={args.random_seed}).",
                file=sys.stderr,
            )
        else:
            names = collect_unique_from_lines(args.from_lines, limit=args.limit)

    if not names:
        print("Нет строк для обработки.", file=sys.stderr)
        return 2

    existing: list[dict[str, Any]] = []
    existing_file_legacy_model: str | None = None
    if args.merge_output and args.output.is_file():
        try:
            blob_pre = json.loads(args.output.read_text(encoding="utf-8"))
            if isinstance(blob_pre, dict) and isinstance(blob_pre.get("entries"), list):
                existing = [e for e in blob_pre["entries"] if isinstance(e, dict)]
                m = blob_pre.get("model")
                if isinstance(m, str) and m.strip():
                    existing_file_legacy_model = m.strip()
        except (OSError, json.JSONDecodeError):
            pass

    if args.merge_output and existing:
        skip_cf = collect_raw_casefolds_already_having_model(
            existing,
            args.model,
            legacy_flat_model=existing_file_legacy_model,
            mask_enumeration_numbers=bool(args.mask_enumeration_numbers),
        )
        if skip_cf:
            if args.mask_enumeration_numbers:
                names = [
                    n
                    for n in names
                    if mask_organization_name_enumeration_numbers_v1(n).casefold() not in skip_cf
                ]
            else:
                names = [n for n in names if n.casefold() not in skip_cf]

    names_for_first_model = list(names)
    if not names_for_first_model and not second_model:
        print("После слияния с выходным файлом не осталось новых имён.", file=sys.stderr)
        return 0

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not args.dry_run and not api_key:
        print("Задайте OPENROUTER_API_KEY или используйте --dry-run.", file=sys.stderr)
        return 2

    names_sent_first = len(names_for_first_model)
    names_sent_second = 0

    bs = max(1, int(args.batch_size))
    batches_m1: list[list[str]] = []
    for i in range(0, len(names_for_first_model), bs):
        batches_m1.append(names_for_first_model[i : i + bs])

    if args.dry_run:
        if batches_m1:
            first = batches_m1[0]
            api_batch = (
                [mask_organization_name_enumeration_numbers_v1(x) for x in first]
                if args.mask_enumeration_numbers
                else list(first)
            )
            print(f"name_kind={name_kind} (длина system: {len(system_prompt)} симв.)", file=sys.stderr)
            print(f"--model={args.model} (первый батч):", file=sys.stderr)
            print(json.dumps(api_batch, ensure_ascii=False)[:4000])
            if len(json.dumps(api_batch, ensure_ascii=False)) > 4000:
                print("… [усечено]", file=sys.stderr)
        if second_model:
            print(f"--second-model={second_model}: тот же список имён после первой модели (в --dry-run не вызывается).", file=sys.stderr)
        return 0

    assert api_key
    all_m1: list[dict[str, Any]] = []
    if batches_m1:
        all_m1, err_m1 = asyncio.run(
            run_all_batches_async(
                batches_m1,
                api_key=api_key,
                model=args.model,
                system_prompt=system_prompt,
                temperature=float(args.temperature),
                read_timeout_s=int(args.timeout),
                max_retries=int(args.max_retries),
                concurrency=int(args.concurrency),
                sleep_after=float(args.sleep),
                mask_enumeration_numbers=bool(args.mask_enumeration_numbers),
                adaptive_backoff=bool(args.adaptive_backoff),
                adaptive_min_concurrency=int(args.adaptive_min_concurrency),
                adaptive_max_gap_s=float(args.adaptive_max_gap_s),
            )
        )
        if err_m1:
            print(f"Ошибок батчей (--model): {len(err_m1)} из {len(batches_m1)}.", file=sys.stderr)
            return 1

    merged = merge_entries(
        existing,
        all_m1,
        key_raw_casefold=True,
        legacy_flat_model_for_existing=existing_file_legacy_model,
        new_batch_model=args.model,
    )

    model_last_run: str = args.model
    all_m2: list[dict[str, Any]] = []

    if second_model:
        names_m2 = raws_missing_model_slot(
            merged,
            second_model,
            legacy_flat_model=None,
        )
        names_sent_second = len(names_m2)
        if names_m2:
            print(
                f"Вторая модель {second_model}: к отправке уникальных raw: {names_sent_second}.",
                file=sys.stderr,
            )
        batches_m2: list[list[str]] = []
        for i in range(0, len(names_m2), bs):
            batches_m2.append(names_m2[i : i + bs])
        if batches_m2:
            all_m2, err_m2 = asyncio.run(
                run_all_batches_async(
                    batches_m2,
                    api_key=api_key,
                    model=second_model,
                    system_prompt=system_prompt,
                    temperature=float(args.temperature),
                    read_timeout_s=int(args.timeout),
                    max_retries=int(args.max_retries),
                    concurrency=int(args.concurrency),
                    sleep_after=float(args.sleep),
                    mask_enumeration_numbers=bool(args.mask_enumeration_numbers),
                    adaptive_backoff=bool(args.adaptive_backoff),
                    adaptive_min_concurrency=int(args.adaptive_min_concurrency),
                    adaptive_max_gap_s=float(args.adaptive_max_gap_s),
                )
            )
            if err_m2:
                print(f"Ошибок батчей (--second-model): {len(err_m2)} из {len(batches_m2)}.", file=sys.stderr)
                return 1
            merged = merge_entries(
                merged,
                all_m2,
                key_raw_casefold=True,
                legacy_flat_model_for_existing=None,
                new_batch_model=second_model,
            )
            model_last_run = second_model

    models_union: set[str] = set()
    for ent in merged:
        bmm = ent.get("by_model")
        if isinstance(bmm, dict):
            models_union.update(bmm.keys())
    out_doc: dict[str, Any] = {
        "dictionary_draft_format_version": DICTIONARY_DRAFT_FORMAT_VERSION,
        "model": args.model,
        "model_last_run": model_last_run,
        "models_in_dictionary": sorted(models_union),
        "name_kind": name_kind,
        "source": str(args.from_jsonl or args.from_lines),
        "entries": merged,
        "http": {
            "client": "httpx-async",
            "concurrency_initial": int(args.concurrency),
            "adaptive_backoff": bool(args.adaptive_backoff),
            "adaptive_min_concurrency": int(args.adaptive_min_concurrency),
            "adaptive_max_gap_s": float(args.adaptive_max_gap_s),
            "sleep_baseline_s": float(args.sleep),
            "batch_size": int(args.batch_size),
        },
    }
    if second_model:
        out_doc["second_model"] = second_model
        out_doc["models_compared"] = [args.model, second_model]
    if args.mask_enumeration_numbers:
        out_doc["mask_enumeration_numbers_v1"] = True
    if args.full_unique_sample is not None:
        out_doc["sampling"] = {
            "mode": "full_unique_uniform",
            "sample_size_requested": args.full_unique_sample,
            "random_seed": args.random_seed,
            "population_unique_strings": population_unique,
            "strings_sent_to_model_this_run": names_sent_first,
            "strings_sent_to_primary_model": names_sent_first,
            "strings_sent_to_second_model": names_sent_second,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Записано {len(merged)} записей "
        f"(ответов API: {args.model}→{len(all_m1)}"
        f"{f', {second_model}→{len(all_m2)}' if second_model else ''}): "
        f"{args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
