#!/usr/bin/env python3
"""lorien killer demo — what Mem0 cannot do.

Demonstrates:
1. Rule system (priority 100 prohibition stored from past conversation)
2. Semantic vector search (finds 'shellfish allergy' when querying 'seafood')
3. Automatic contradiction detection (new recommendation contradicts stored rule)

Usage:
    cd ~/Documents/lorien
    .venv/bin/python demo_killer.py
    .venv/bin/python demo_killer.py --model haiku   # with LLM contradiction check
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from lorien import LorienMemory


def run_demo(model: str | None = None, db_path: str | None = None) -> None:
    # Use temp DB for clean demo
    if db_path is None:
        db_path = str(Path(tempfile.mkdtemp()) / "demo_db")

    print("\n" + "═" * 60)
    print("  🌳 lorien — Killer Demo")
    print("  (what Mem0 cannot do)")
    print("═" * 60)

    mem = LorienMemory(db_path=db_path, model=model, enable_vectors=True)
    has_vectors = mem.vectors is not None

    # ── PAST: 3 months ago ──────────────────────────────────────────
    print("\n📅 [3개월 전] 유저와 나눈 대화:")
    past = [
        {"role": "user", "content": "참고로 나 조개류 알레르기 엄청 심해. 굴, 홍합, 새우 먹으면 응급실 가야 해."},
        {"role": "assistant", "content": "중요한 정보 알려주셔서 감사해요. 조개류 관련 음식은 절대 추천하지 않을게요."},
    ]
    for m in past:
        print(f"  {m['role'].upper()}: {m['content']}")

    r1 = mem.add(past, user_id="아부지")
    print(f"\n  → 저장됨: {r1['entities']} entities, {r1['facts']} facts, {r1['rules']} rules")

    # ── TODAY: new conversation ──────────────────────────────────────
    print("\n📅 [오늘] 새로운 대화:")
    today = [
        {"role": "user", "content": "오늘 저녁 뭐 먹을까?"},
        {"role": "assistant", "content": "한남동에 새로 생긴 굴 구이 맛집 어때요? 웨이팅 없다고 하더라고요."},
    ]
    for m in today:
        print(f"  {m['role'].upper()}: {m['content']}")

    r2 = mem.add(today, user_id="아부지")
    print(f"\n  → 저장됨: {r2['entities']} entities, {r2['facts']} facts, {r2['rules']} rules")

    # ── FEATURE 1: Semantic Search ───────────────────────────────────
    print("\n" + "─" * 60)
    print("⚡ Feature 1: 시맨틱 벡터 검색")
    print('   쿼리: "해산물 제한"')
    if has_vectors:
        results = mem.search("해산물 제한", user_id="아부지", limit=3)
        if results:
            for r in results:
                score_bar = "█" * int(r["score"] * 10)
                print(f"   [{r['type']}] {score_bar} ({r['score']:.2f}) {r['memory'][:60]}")
        else:
            print("   (결과 없음 — 더 많은 데이터 필요)")
    else:
        print("   ⚠ sentence-transformers 미설치 (pip install lorien[vectors])")

    # ── FEATURE 2: Hard Rules ────────────────────────────────────────
    print("\n" + "─" * 60)
    print("⚡ Feature 2: 규칙 시스템 (Mem0에 없음)")
    rules = mem.get_entity_rules("아부지")
    if rules:
        for r in rules:
            emoji = "🔴" if r["priority"] >= 90 else "🟡"
            print(f"   {emoji} [{r['rule_type']} p{r['priority']}] {r['text'][:70]}")
    else:
        print("   (규칙 없음 — LLM 모드에서 더 잘 추출됨)")

    # ── FEATURE 3: Contradiction Detection ──────────────────────────
    print("\n" + "─" * 60)
    print("⚡ Feature 3: 모순 감지 (Mem0에 없음)")
    contradictions = mem.get_contradictions()
    if contradictions:
        print(f"   ⚠️  {len(contradictions)}개 모순 감지!")
        for c in contradictions:
            print(f"\n   충돌 A: {c['fact_a']['text'][:70]}")
            print(f"   충돌 B: {c['fact_b']['text'][:70]}")
    else:
        if model:
            print("   ✓ 모순 없음 (또는 LLM이 같은 대화 내 모순을 감지하지 못함)")
        else:
            print("   → LLM 없이는 heuristic만 작동 (--model haiku 로 실행 시 LLM 확인)")
        print("\n   📝 직접 확인:")
        all_facts = mem.get_all(user_id="아부지")
        allergy_facts = [f for f in all_facts if any(
            kw in f["memory"].lower() for kw in ["알레르기", "allerg", "조개", "shellfish"]
        )]
        oyster_facts = [f for f in all_facts if any(
            kw in f["memory"].lower() for kw in ["굴", "oyster", "구이"]
        )]
        if allergy_facts:
            print(f"   알레르기 관련: '{allergy_facts[0]['memory'][:60]}'")
        if oyster_facts:
            print(f"   굴 추천 관련: '{oyster_facts[0]['memory'][:60]}'")
        if allergy_facts and oyster_facts:
            print("   → 이 둘은 명백히 충돌함! (벡터 + LLM 시 자동 CONTRADICTS 엣지 생성)")

    # ── COMPARISON ───────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  📊 Mem0 vs lorien")
    print("─" * 60)
    print("  기능                    Mem0    lorien")
    print("  대화 메모리 추출          ✅      ✅")
    print("  시맨틱 벡터 검색          ✅      ✅")
    print("  로컬 (서버 없음)          ❌      ✅")
    print("  비용                     $249/월  $0")
    print("  우선순위 규칙 시스템       ❌      ✅")
    print("  인과 추론 (CAUSED)        ❌      ✅")
    print("  자동 모순 감지            ❌      ✅")
    print("═" * 60)
    print("  lorien — local. free. structured. open source.")
    print("  https://github.com/paperbags1103-hash/lorien")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="lorien killer demo")
    parser.add_argument("--model", default=None, help="LLM model e.g. haiku (uses OpenClaw gateway)")
    parser.add_argument("--db", default=None, help="DB path (default: temp dir)")
    args = parser.parse_args()
    run_demo(model=args.model, db_path=args.db)
