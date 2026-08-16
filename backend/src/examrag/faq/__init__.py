"""Past paper FAQ generation: extraction, normalization, clustering, frequency.

Past papers carry no structure beyond numbering — unlike study material, which
gets heading-aware chunking. This package finds the individual questions inside
already-stored chunks, groups the ones that are semantically the same question
asked again in a different year or a different paper, and reports how often
each group appears. No LLM is involved: extraction is regex-based and grouping
uses the same embedding model as retrieval, so the result is deterministic and
needs nothing beyond what ingestion already produced.
"""
