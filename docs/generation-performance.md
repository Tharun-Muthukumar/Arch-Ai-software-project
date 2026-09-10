# Generation pipeline performance

Measured on 2026-09-09 with the local `qwen3:8b` model and an unfamiliar
quantum-magnetometer calibration brief. The benchmark is reproducible with:

```bash
backend/.venv/bin/python scripts/benchmark-generation.py
```

| Measurement | Before | After | Change |
|---|---:|---:|---:|
| LLM calls | 2 | 1 | 50% fewer |
| End-to-end generation time | 49.41 s | 40.43 s | 8.98 s faster (18.2%) |

The before duration is a controlled reconstruction: the optimized run's exact
section timings are serialized to match the previous scheduler, then the
removed `architecture-selection` call is replayed and measured against the
same extracted requirements. That removed call took 8.98 seconds. Parallel
local stages saved another 3 ms in this workload; model inference was the
dominant cost.

The optimized run made only the bundled unfamiliar-domain extraction call.
Known blueprint domains make zero generation LLM calls (previously one for
architecture selection). The representative output retained 6 functional
requirements, 5 actors, 8 entities, 6 API groups, and 3 scored architecture
options. Correctness and isolation are covered by the full test suite plus
targeted call-count, parallelism, cache-isolation, selective-refresh, and SSE
progress tests.
