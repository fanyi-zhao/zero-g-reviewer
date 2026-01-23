# Python Migration Guidelines (v2 -> v3)

We are currently migrating our codebase from Legacy Lib v2 to Modern Lib v3.

## Migration Rules

1. **Deprecation**: Flag any usage of `legacy_lib.old_module`.
2. **New Patterns**: 
   - Use `modern_lib.context.get()` instead of `legacy_lib.get_context()`.
   - All async functions must use `await` syntax; no `yield from`.

## Code Quality

- **Type Hints**: All new functions MUST have type hints.
- **Docstrings**: Google-style docstrings are required for all public methods.

## Forbidden Patterns

- Do not use global variables for configuration.
- Do not catch bare `Exception`.

If you see these patterns, mark them as **Major** issues.
