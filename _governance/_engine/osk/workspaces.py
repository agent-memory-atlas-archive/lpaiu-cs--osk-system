"""일회성 작업 공간 — 하네스가 대화나 작업마다 새로 만드는 작업 폴더(시행령 §3 9항).

판별은 작업 폴더의 경로 모양으로 한다(Mechanism §6-2 6항): 하네스가 관리하는 뿌리 폴더와
그 아래의 모양이며, 확인한 하네스 판본을 함께 적는다. 엔진의 규칙(`RULES`)과 동기화되는 대장
`_ledger/workspaces.jsonl`의 규칙(`kind: "rule"`)이 같은 형식이다. Git 저장소는 판별하지
않는다 — 그 키는 저장소 동일성으로 구별된다.

일회성 작업 공간의 세션 키는 결속하지 않고 그 키에 선 결속도 따르지 않는다. 쓰기 도구는 세션
키만 받으므로, 포착이 판별한 키를 이 기기의 목록에 남겨(`remember`) 결속 판정
(`write.resolve_session`·`write.bind_after_write`)이 같은 판정을 따르게 한다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import core

LEDGER = core.LEDGER / "workspaces.jsonl"

# 운영 기기(Windows)에서 확인한 규칙이다(2026-10-11, #179). 다른 OS의 경로와 규칙이 없는 하네스는
# 설치하는 에이전트가 같은 형식으로 대장에 더한다(SETUP의 일회성 작업 공간).
RULES = (
    {"kind": "rule", "harness": "codex", "os": "nt", "version": "0.159.2",
     "root": "~/Documents/Codex", "shape": r"\d{4}-\d{2}-\d{2}/(?:task(?:-\d+)?/)?[^/]+",
     "note": "Codex 데스크톱의 대화 폴더 — 이 폴더에서 돈 Claude Code 세션도 같다"},
    {"kind": "rule", "harness": "claude", "os": "nt", "version": "2.1.281",
     "root": "%APPDATA%/Claude/scratch-workspaces",
     "shape": r"[0-9a-f-]{36}/[0-9a-f-]{36}/scratch-\d{4}-\d{2}-\d{2}-[0-9a-f]{6}",
     "note": "Claude 데스크톱의 scratch 작업 공간"},
    {"kind": "rule", "harness": "antigravity", "os": "nt", "version": "2.17.0",
     "root": "~/.gemini/antigravity/playground", "shape": r"[a-z]+(?:-[a-z]+)+",
     "note": "Antigravity의 playground"},
)


def rules() -> list[dict]:
    """이 기기의 OS에 맞는 엔진 규칙과 대장 규칙. 대장을 읽지 못하면 엔진 규칙만 쓴다."""
    try:
        extra = [r for r in core.ledger_read(LEDGER) if r.get("kind") == "rule"]
    except (OSError, ValueError):
        extra = []
    return [r for r in (*RULES, *extra) if r.get("os") in (None, os.name)]


def _root(rule: dict) -> Path | None:
    text = os.path.expandvars(os.path.expanduser(str(rule.get("root") or "")))
    if not text or "%" in text or "$" in text:     # 정의되지 않은 환경 변수
        return None
    try:
        return Path(text).resolve()
    except OSError:
        return None


def judge(harness: str, cwd: str | None, version: str | None = None) -> dict | None:
    """작업 폴더가 어느 규칙의 뿌리 아래면 그 판정, 아니면 None. 뿌리 아래에서 규칙에 없는 모양이나
    규칙을 확인한 판본과 다른 하네스 판본은 일회성으로 둔 채 `warning`으로 알린다."""
    if not cwd:
        return None
    try:
        path = Path(cwd).resolve()
    except OSError:
        return None
    for rule in rules():
        root = _root(rule)
        try:
            rel = path.relative_to(root) if root else None
        except ValueError:
            rel = None
        if rel is None or not rel.parts:
            continue
        if any((p / ".git").exists() for p in [path, *path.parents][:len(rel.parts)]):
            return None             # Git 저장소의 키는 저장소 동일성으로 구별된다
        out = {"one_off": True, "harness": rule["harness"], "root": rule["root"],
               "cwd": str(path), "version": version}
        if not re.match(rf"(?:{rule['shape']})(?:/|$)", rel.as_posix()):
            out["warning"] = (f"`{rule['root']}` 아래의 규칙에 없는 모양({rel.as_posix()})이다 — 결속하지 "
                              "않았다. 일회성 작업 공간의 규칙을 다시 확인한다(SETUP의 일회성 작업 공간)")
        elif version and harness == rule["harness"] and version != rule.get("version"):
            out["warning"] = (f"{harness} {version}은 규칙을 확인한 판본({rule.get('version')})과 다르다 — "
                              "일회성 작업 공간의 규칙을 다시 확인한다(SETUP의 일회성 작업 공간)")
        return out
    return None


def add(harness: str, root: str, shape: str, version: str, note: str = "") -> dict:
    """규칙 하나를 대장에 더한다 — 규칙이 없는 하네스의 일회성 작업 공간을 설치하는 에이전트가
    적는다. 이 기기의 OS에 묶는다. 대장 행도 작업 트리의 변경이라 변경 잠금 안에서 쓴다."""
    re.compile(shape)
    if not all(isinstance(v, str) and v.strip() for v in (harness, root, shape, version)):
        raise ValueError("harness, root, shape and version are required")
    with core.mutation_lock():
        return core.ledger_append(LEDGER, {"kind": "rule", "harness": harness, "os": os.name,
                                           "version": version, "root": root, "shape": shape,
                                           "note": note})


def _keys() -> Path:
    return core.local_lock_path("osk-one-off-keys.txt").with_suffix(".txt")


def remember(key: str | None) -> None:
    """이 기기에서 일회성 작업 공간으로 판별한 세션 키를 남긴다 — 한 줄에 하나, 덧붙이기만 한다."""
    key = (key or "").strip()
    if key and not is_one_off(key):
        path = _keys()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(key + "\n")


def is_one_off(key: str | None) -> bool:
    key = (key or "").strip()
    try:
        return bool(key) and key in _keys().read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
