# Security-Focused Review Guidelines

Please prioritize **security vulnerabilities** above all else.

## Critical Checks (Blockers)

- **Secrets**: Ensure no credentials, API keys, or tokens are committed.
- **Injection**: Check for SQL injection in raw queries and XSS in templates.
- **Auth**: Verify that all new endpoints have `@login_required` or equivalent checks.
- **Input Validation**: Ensure all user inputs are typed and validated (Pydantic models preferred).

## Testing

- Ask for regression tests for any security fix.
- Ensure tests do not mock out the authentication layer completely.

## Ignore

- You can be lenient on code style (PEP8) violations unless they severely impact readability.
- Ignore changes in the `docs/` directory.
