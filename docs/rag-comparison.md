# E-Judgment compared with other RAG designs

This page places E-Judgment ([architecture](architecture.md)) among the common types of retrieval-augmented generation (RAG). In short, E-Judgment is a **hybrid-retrieval RAG with a verification layer**. It is not a graph RAG.

## The designs

| | Naive (vector) RAG | Hybrid RAG | Graph RAG | **E-Judgment** |
|---|---|---|---|---|
| **Index** | Chunk embeddings | Chunk embeddings and a keyword index; sometimes also a graph | A knowledge graph of entities and relations extracted by an LLM, often with summaries of communities in the graph | Chunk embeddings (pgvector HNSW), Postgres full-text vectors, and exact citation and case-name lookup |
| **Retrieval** | Top-k nearest neighbours | Lexical and dense results fused (e.g. RRF), often reranked | Graph traversal or community summaries, sometimes plus vectors | Three channels, RRF, cross-encoder rerank, grouped into cases |
| **Unit of evidence** | A chunk | A chunk | A node, an edge or an LLM summary | An exact span of the judgment's text, with its page if verified |
| **Answer** | Free text from the LLM | Free text from the LLM | Free text, often drawing on generated summaries | Claims that must quote a source and be entailed by it, assembled on the server |
| **Main strength** | Simple; good at paraphrase | Exact terms *and* paraphrase | Questions about connections and the corpus as a whole | Precise lookup plus traceable, checked answers |
| **Main weakness** | Misses exact terms (citations, section numbers) | Fusion weights need tuning; still chunk-local | Costly to build; extracted facts can be wrong and are hard to trace | Chunk-local; no reasoning across cases |

"Hybrid RAG" means two different things:

- **Sparse + dense.** Keyword and embedding retrieval combined. This is what E-Judgment does.
- **Vector + graph.** A vector index combined with a knowledge graph, e.g. retrieving chunks and then expanding along graph edges. E-Judgment does not do this.

## Where E-Judgment differs from plain hybrid RAG

1. **Exact channels come first.** A neutral citation or case name is resolved deterministically before any fusion. Lawyers often know the case they want, and embeddings can't reliably tell `[2019] GHASC 12` from `[2019] GHASC 21`. Citation and case-name questions score 1.0 Recall@20 on the draft gold set.
2. **Case-level results.** Passages are capped per case and grouped into cases. Re-published copies of one judgment (about 10% of the corpus) collapse into one result. Plain RAG returns chunks, so one long judgment can fill the whole context.
3. **Verification after generation.** Most RAG designs trust the model to use the context it was given. Here every claim must:
   - quote a cited passage verbatim;
   - add no citation absent from that passage, and no page reference at all;
   - be entailed by the passage, according to a local NLI model.

   Anything else is removed, and the system abstains when nothing survives.
4. **The server owns provenance.** Citations, links, attribution and page pinpoints come from the database, never from the model. A pinpoint appears only for a verified page.
5. **Rights and reproducibility are in the schema.** Each source carries a `rights_status`. Each evaluation run records its models, settings and a fingerprint of the corpus.

## What graph RAG would offer, and its risks

Case law is naturally a graph: judgments cite judgments and statutes, and judges, courts and parties recur. A graph could answer questions that chunk retrieval cannot:

- "Which later cases cite *X*?"
- "Is there a line of authority on *Y*?"
- "Which Supreme Court decisions interpret section *Z*?"

**Two ways to build it, with very different trust:**

- **LLM-extracted knowledge graphs** (GraphRAG-style entities, relations and community summaries). The model writes the graph's facts, e.g. "*A* overruled *B*". A wrong edge looks exactly like a right one and has no passage behind it. Using such edges as evidence would break AGENTS.md rule 1 (no fabricated subsequent treatment) and rule 2 (provenance). Indexing about 160,000 chunks this way would also cost far more than the local pipeline.
- **A deterministic citation graph.** Neutral citations (`[YYYY] GHASC n`) and statute references would be extracted from the text with patterns and resolved to judgments in the corpus. Each edge points back to the span where the citation occurs, so it is checkable. It says only "*A* mentions *B*", not "*A* followed *B*" or "*A* overruled *B*". Treatment would still have to be read in the passage.

**How the citation graph could fit in without weakening the guarantees:**

- **Retrieval signal:** a fourth RRF channel or a prior, e.g. passages of cases often cited for the matched issue.
- **Expansion:** after retrieval, add the passages where a top case is cited or discussed, then let the existing quote and NLI checks decide what survives.
- **UI:** "cited by" and "cites" lists on a judgment, each linking to the citing passage.

**Limits that stay:**

- Citation coverage is partial. Older and OCR'd judgments often lack neutral citations, and 551 judgments have no text.
- Absence from the graph doesn't mean a case was never cited (rule 3).

## Other variants, briefly

- **Agentic or multi-step RAG:** the LLM issues several searches and reasons between them. It suits multi-part questions, but each step is a model decision that needs verifying. It is deferred by AGENTS.md rule 8 (no agent frameworks in the MVP).
- **Long-context "no retrieval":** the whole judgment goes into the prompt. It works for one known case, but not for search across 8,800 judgments. Local models also have small context windows.
- **Fine-tuned retrievers or rerankers:** a legal-domain reranker is listed as a known gap (M2). It must wait for lawyer-reviewed gold questions, so that tuning isn't fitted to unreviewed drafts.

## Summary

E-Judgment chose precision and traceability over breadth: exact lookup plus hybrid retrieval for recall, and post-generation verification for trust. Graph RAG's strength, reasoning across connected cases, is the natural next extension. It fits only as a deterministic citation graph whose edges point back to source text, not as an LLM-written knowledge graph.
