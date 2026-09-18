class InterpretationError(Exception):
    """Unusable provider response; message is safe to log without raw input."""


class GuardrailError(ValueError):
    """Invalid extracted directive; contains only controlled validation feedback."""


class OptimizationError(Exception):
    """No certified optimal solution was obtained."""


class ReplayError(ValueError):
    """The returned plan violates a deterministic replay check."""
