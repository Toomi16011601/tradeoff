"""Conservative accidental-disclosure checks; this is not a secret scanner."""
import re


class SensitiveDataError(ValueError):
    """A recognized private field/value cannot enter a portable artifact."""


class ExecutionUnavailable(ValueError):
    """An intentional backend limitation with a public, non-sensitive reason.

    Callbacks may use this for a safe explanation of unsupported simulation.
    Ordinary callback exception messages are omitted from portable evidence.
    """


_PRIVATE_KEYS = frozenset({
    'apikey', 'apisecret', 'secretkey', 'clientsecret', 'password', 'passwd',
    'privatekey', 'accesstoken', 'refreshtoken', 'authtoken', 'sessiontoken',
    'authorization', 'cookie', 'cookies', 'credentials', 'credential',
    'email', 'emailaddress', 'owneremail', 'useremail', 'phone', 'phonenumber',
    'accountnumber', 'accountid', 'brokeraccount', 'walletprivatekey',
    'homeaddress', 'streetaddress', 'socialsecuritynumber', 'ssn',
})
_PRIVATE_TEXT = re.compile(
    r'-----BEGIN (?:[A-Z0-9 ]*PRIVATE KEY)-----'
    r'|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'
    r'|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'
    r'|\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b'
    r'|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}'
    r'|(?:/Users/|/home/)[^/\s]+(?:/|\b)'
    r'|[A-Z]:[\\/]Users[\\/][^\\/\s]+', re.IGNORECASE,
)


def reject_sensitive_data(value, *, label='Data'):
    """Reject recognized credentials/contact/account fields and strong patterns.

    Do not echo values or silently change replay inputs/hashes. Arbitrary names,
    proprietary strategies and unknown secret formats still need human review.
    """
    def visit(item, ancestors, depth):
        if depth > 256:
            raise ValueError(f'{label} exceeds the supported nesting depth')
        if isinstance(item, str):
            if _PRIVATE_TEXT.search(item):
                raise SensitiveDataError('Recognized sensitive data; use sanitized simulation inputs')
        elif isinstance(item, (dict, list, tuple)):
            if id(item) in ancestors:
                raise ValueError(f'{label} contains a cycle')
            parents = ancestors | {id(item)}
            children = item.items() if isinstance(item, dict) else enumerate(item)
            for key, child in children:
                if isinstance(key, str):
                    visit(key, parents, depth + 1)
                    normalized = re.sub(r'[^a-z0-9]', '', key.lower())
                    empty = child is None or (isinstance(child, (str, list, tuple, dict)) and len(child) == 0)
                    if normalized in _PRIVATE_KEYS and not empty:
                        raise SensitiveDataError('Recognized sensitive field; remove credentials or personal data')
                visit(child, parents, depth + 1)
    visit(value, set(), 0)


def callback_error(exc):
    """Keep deliberate safe limitations, omit arbitrary exception messages."""
    from .diagnostics import record_exception
    record_exception(exc)
    if isinstance(exc, ExecutionUnavailable):
        try:
            reject_sensitive_data(str(exc))
        except SensitiveDataError:
            return 'Execution unavailable; sensitive diagnostic omitted'
        return f'Execution unavailable: {exc}'
    return f'Callback failed ({type(exc).__name__}); exception message omitted for privacy'
