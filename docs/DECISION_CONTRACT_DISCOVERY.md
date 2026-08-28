# Contract Discovery v0

Isolated experiment. **Does not change the retrieval execution pipeline.**

**Boundary:** Code owns the meta-schema and freeze/gap loop. LLM owns decision *ids*, questions, outcomes, and sufficiency *content*. See `FRAMEWORK_BOUNDARY.md`. Do not promote package/GPU field names into a permanent global enum.

## Hypothesis

A small, schema-constrained LLM (or offline heuristic) pass over:

```text
TASK.md
+ compact PageState / structure / observation samples
```

can produce a **task-specific Research Contract** that:

1. Defines the **subject** (what counts as an instance)
2. Lists **required observables**
3. Lists **semantic decisions** with fixed outcome enums (always including `UNKNOWN`)
4. States **sufficiency** and **missing_to_solve**
5. **Explains** why a run with `rankable=0` failed (which decisions stayed UNKNOWN)

Code owns the **meta-schema**, validation, and gap analysis.  
LLM only fills **content**.

## Why not MEMBER_ROLE as the architecture?

`TARGET | NAVIGATION | ACTION | …` is a useful *structural feature layer* for list harvest, but it is still a pre-chosen ontology. Different tasks (packages, GPUs, literature synthesis) need different decisions. Those decisions should come from a **contract**, not a global enum.

`TARGET` as a *primitive meaning* (“instance of the contract’s subject”) remains valid; the contract defines what the subject is.

## Meta-schema (fixed in code)

```json
{
  "schema_version": "0.1",
  "subject": { "name": "...", "definition": "..." },
  "observables": ["..."],
  "decisions": [
    {
      "id": "...",
      "question": "...",
      "outcomes": ["...", "UNKNOWN"],
      "evidence_required": ["..."],
      "unknown_conditions": ["..."]
    }
  ],
  "sufficiency": {
    "required": ["..."],
    "blocking_unknowns": ["..."]
  },
  "missing_to_solve": ["..."]
}
```

## Success criterion (v0)

Not “pretty JSON”.

> **Can the contract explain why the packages run produced 0 rankable candidates, and name the semantic gaps (board_type, detail_link, price_scope, …)?**

If yes → architecture direction validated → next: freeze + typed decision execution.  
If no → improve recon context / schema before any pipeline refactor.

## How to run

```bash
# Offline heuristic (always works)
python scripts/run_contract_discovery_v0.py --fixture

# Against a real run directory
python scripts/run_contract_discovery_v0.py \
  --run-dir runs/2026-08-24T08-01-36_compare_packages_dec2026

# Optional Ollama fill
python scripts/run_contract_discovery_v0.py --run-dir PATH --llm
```

Outputs `contract_discovery_v0.json` in the run dir (or fixture dir).

## Explicitly out of scope (v0)

- Full multi-host recon/convergence loop and FREEZE state machine
- Changing harvest / MinAC / eligibility / shortlist code
- AX / OCR / multi-modal
- Self-refining SPEC_GAP loop into production

## Relation to MEMBER_ROLE

Keep `member_role.py` as a **feature extractor** for structure.members.  
Later, `subject_instance` (or equivalent) from the **contract** becomes the admissibility policy; MEMBER_ROLE is not the permanent ontology.


## Modes CD0 / CD1 / CD2 (2026-08-26)

| Mode | Input | Role |
|------|--------|------|
| CD0 | task only | Provisional contract |
| CD1 | task + samples one-shot | Prior default |
| CD2 | provisional then refine with samples | Iterative grounding hypothesis |

Runner: `scripts/run_contract_discovery_campaign_v0.py`.

## End-to-end FREEZE loop (2026-08-27)

Production path for step 1 (generic agent):

```text
synthesize_and_freeze_contract(task_text)
  → CD0 provisional
  → gap-check (LLM or structural)
  → refine / gap_revise until ready_to_freeze or max_passes
  → contract["frozen"] = true|false
```

Batch over `tasks/batch_v0`:

```bash
python scripts/run_contract_synthesis_batch_v0.py \
  --tasks-dir tasks/batch_v0 \
  --outdir ./evals/contract_synthesis \
  --llm
```

Code owns the loop and meta-schema; LLM owns claim content and freeze judgment.
See `FRAMEWORK_BOUNDARY.md`.
