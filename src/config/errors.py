
from pathlib import Path


class StateDirUnavailableError(RuntimeError):

    def __init__(self, path: Path, cause: OSError) -> None:
        self.path = path
        self.cause = cause
        super().__init__(
            f"CloudeCode state directory unavailable: could not create "
            f"'{path}' ({cause.__class__.__name__}: {cause}). Set "
            f"CLOUDE_STATE_DIR to a writable path and restart. Refusing "
            f"to fall back to a temp directory for state you depend on."
        )
