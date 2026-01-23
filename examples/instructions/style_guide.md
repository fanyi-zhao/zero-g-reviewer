# Team Style Guide

## General Philosophy

- **Readability counts**: Prefer simple code over clever one-liners.
- **Explicit is better than implicit**: Avoid magic numbers and hidden state.

## Specific Preferences

- Use `pathlib.Path` instead of `os.path` strings.
- Use `f-strings` for string formatting.
- Tests should use `pytest` fixtures, not `unittest.TestCase` classes.
- Variable names should be descriptive (`user_account` not `u`).

## Review Tone

- Be encouraging! Use emojis 🎉
- Phrase suggestions as questions ("Have you considered...?") rather than commands ("Change this to...").
