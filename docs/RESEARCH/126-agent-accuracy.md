# 126 — What makes LLM agents more accurate, and what fits here?

**Date:** 2026-10-29 · **Confidence:** high on the findings as each paper reports them; medium on how far they transfer to this platform's small models

## Question

The operator asked what improves agent accuracy, and what happens when a model hallucinates.

## Sources

| Source | URL | Fetched |
|---|---|---|
| Wang et al., Self-Consistency Improves Chain of Thought Reasoning (2022) | https://arxiv.org/abs/2203.11171 | 2026-10-29 |
| Dhuliawala et al., Chain-of-Verification Reduces Hallucination (2023) | https://arxiv.org/abs/2309.11495 | 2026-10-29 |
| Huang et al., Large Language Models Cannot Self-Correct Reasoning Yet (2023) | https://arxiv.org/abs/2310.01798 | 2026-10-29 |
| Zheng et al., Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena (2023) | https://arxiv.org/abs/2306.05685 | 2026-10-29 |
| Anthropic, Introducing Contextual Retrieval (2024) | https://www.anthropic.com/news/contextual-retrieval | 2026-10-29 |
| Kong et al., Evaluating LLMs in Finance Requires Explicit Bias Consideration (2026) | https://arxiv.org/html/2602.14233 | 2026-10-29 |
| Li, Wang and Ma, Mitigating Look-Ahead Bias in Financial Backtesting with LLMs (2026) | https://arxiv.org/pdf/2605.24564 | 2026-10-29 |

## Findings

1. Without outside feedback, self-correction does not reliably help and sometimes hurts (Huang).
2. Chain-of-Verification works: draft the answer, plan questions that check it, answer each one separately, then revise. It reduced hallucinations on list, QA and long-form tasks (Dhuliawala).
3. Self-consistency: sampling several reasoning paths and taking the majority gained +17.9% on GSM8K and +12.2% on AQuA (Wang).
4. A GPT-4 judge agreed with humans over 80% of the time. Judges favour position, length and their own answers (Zheng).
5. Adding context to chunks plus BM25 cut top-20 retrieval failures from 5.7% to 2.9%; reranking cut them to 1.9% (Anthropic).
6. LLMs in finance show five biases: look-ahead, survivorship, narrative, objective and cost. Of 164 papers reviewed, 26.8% acknowledged look-ahead and 1.2% addressed survivorship (Kong).
7. Models memorise how stocks moved during their training period. Correcting for that memorisation cut in-sample returns by up to 67.1% (Li, Wang and Ma).

## Decision

Built first: the code-side grounding check, a test set with scores, and prompt fingerprints (ADR-088). The rest of the ranked list is in TASKS (T-4186 to T-4192).

## Not found

No study on 7B–120B open models doing knowledge QA over a private repository, which is this platform's case. The test set is how that gets measured here.
