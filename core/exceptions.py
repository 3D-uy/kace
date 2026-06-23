# core/exceptions.py
#
# Custom Exception classes for KACE.
# Defining exceptions in a dedicated module prevents circular imports
# between wizard modules and orchestrators.

class WizardExit(Exception):
    """Exception raised when the wizard is exited by the user (quit or cancelled)."""
    pass


class GenerationError(Exception):
    """Exception raised when config generation cannot complete safely.

    Replaces sys.exit(1) inside generate_config() so that library callers
    (tests, automation wrappers) can catch and inspect the failure rather
    than having the process killed underneath them.

    Attributes:
        message: Human-readable description of the failure.
        todos:   List of (section, key) tuples for unresolved TODO pins, if any.
    """
    def __init__(self, message: str, todos: list = None):
        super().__init__(message)
        self.todos = todos or []


class DerivationAmbiguityError(Exception):
    """Exception raised when firmware derivation requires user input/clarification.

    Attributes:
        param: The name of the parameter requiring input (e.g. "mcu_family", "bootloader_offset", "comm_interface").
        options: A list or dict of valid options.
        mcu: The MCU name.
    """
    def __init__(self, param: str, options, mcu: str = None):
        super().__init__(f"Derivation requires selection for '{param}'")
        self.param = param
        self.options = options
        self.mcu = mcu

