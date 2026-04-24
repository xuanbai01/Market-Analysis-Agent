# Architecture Decision Records

An ADR captures one architectural decision: what you chose, what you didn't, and why. Future-you (or a new teammate) reads these to understand why the codebase looks the way it does.

## When to write one

Write an ADR when you make a decision that:
- Is expensive to reverse (database choice, monolith vs services, auth model)
- Will surprise someone reading the code without context
- Resolves a real trade-off you debated

You don't need an ADR for "I picked Postgres because it's the default". You do need one for "I picked Postgres over MongoDB because we expect relational joins and the team doesn't know MongoDB".

## How to write one

1. Copy `0000-template.md` to `NNNN-short-title.md` where `NNNN` is the next number.
2. Fill it in. Be brutally honest about the trade-offs, including the ones that might bite later.
3. Commit it in the same PR as the decision it describes.
4. Never rewrite history. If a decision is later reversed, write a new ADR that supersedes the old one. Mark the old one as `Status: Superseded by NNNN`.

## Index

| Number | Title | Status |
|---|---|---|
| 0000 | [Template (copy me)](0000-template.md) | n/a |
| 0001 | [FastAPI + async SQLAlchemy + PostgreSQL](0001-stack-choice.md) | Accepted |
| 0002 | [Deploy to Fly.io, Postgres on Neon](0002-deployment.md) | Accepted |

<!-- Add rows as you add ADRs. -->
