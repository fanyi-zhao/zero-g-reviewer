# Example: MR with Security Fix

This example shows a minimal MR that the agent would review.

## Changed Files

### `src/auth/login.py`

```python
# Before
def login(username: str, password: str) -> Token:
    logger.info(f"Login attempt: {username}, password: {password}")  # BAD!
    
    user = get_user(username)
    if not user:
        raise AuthenticationError("User not found")  # Info leak
    
    if not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid password")  # Info leak
    
    authResult = create_token(user)  # Naming convention
    return authResult


# After (with agent's suggestions applied)
def login(username: str, password: str) -> Token:
    logger.info(f"Login attempt for user: {username}")
    
    user = get_user(username)
    if not user:
        raise AuthenticationError("Invalid username or password")
    
    if not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid username or password")
    
    auth_result = create_token(user)
    return auth_result
```

### `src/auth/tokens.py`

```python
# Before
class Token:
    def is_expired(self) -> bool:
        if self.expiration is None:
            return False  # Bug: None expiration treated as "never expires"
        return datetime.now(UTC) > self.expiration


# After (with agent's suggestions applied)
class Token:
    def is_expired(self) -> bool:
        if self.expiration is None:
            return True  # Tokens without expiration should be treated as expired
        return datetime.now(UTC) > self.expiration
```

## What the Agent Would Find

1. **Blocker**: Password logged in plain text
2. **Major**: Token expiration bug
3. **Major**: Missing rate limiting (would need broader context)
4. **Minor**: User enumeration via error messages
5. **Nit**: Inconsistent naming convention

The agent uses a two-pass approach:
1. **Pass A**: Quick scan to identify files with security/auth patterns
2. **Pass B**: Deep dive into flagged files, using git blame and additional context
