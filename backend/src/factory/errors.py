"""Domain errors for the account factory (CONVENTIONS: explicit errors, no bare except)."""


class FactoryError(Exception):
    """Base class for all account-factory domain errors (TASK-132)."""


class FactoryAccountStoreError(FactoryError):
    """Base for the `factory_accounts` store errors (TASK-132)."""


class FactoryAccountValidationError(FactoryAccountStoreError):
    """A value handed to the store violated a domain invariant before persistence.

    Raised by `create_purchased` when `phone_masked` is not actually masked (does not
    contain the mask char) — a guard against silently persisting a full, unmasked phone
    (PII). The offending value is NEVER included in the message."""


class FactoryAccountNotFoundError(FactoryAccountStoreError):
    """A `transition` (or lookup) referenced a `factory_accounts` row that does not exist.

    Raised by `transition` when no row matches the given account id. The factory loop
    treats this as a programmer/data error (the row should exist for the lifecycle it
    is driving) rather than a recoverable state."""


class IllegalFactoryTransitionError(FactoryAccountStoreError):
    """A requested state transition is not in `ALLOWED_TRANSITIONS[current_state]`.

    Raised by `transition` when the target state is illegal from the row's current
    state (e.g. `purchased → promoted`, skipping registration/probation). Guards the
    lifecycle invariant: an account can only be promoted into the pool after probation."""
