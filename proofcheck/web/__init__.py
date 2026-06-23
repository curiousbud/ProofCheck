"""ProofCheck web layer (FastAPI).

This package is intentionally thin and disposable. It contains **zero** business
logic — it only adapts HTTP requests into a :class:`proofcheck.models.RunConfig`,
calls :func:`proofcheck.pipeline.run`, and serializes the :class:`RunResult` to the
JSON contract defined in :mod:`proofcheck.web.schemas`.
"""
