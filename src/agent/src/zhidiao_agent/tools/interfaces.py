"""Hardware integration contract v0.2.

PC paths remain local paths. A real backend owns upload and remote execution.
The controller must obtain approval before invoking real operations.
"""

from typing import Any, Protocol

from ..models import OperationResult


class HardwareBackend(Protocol):
    @property
    def name(self) -> str:
        """Identify the backend in results and audit records."""
        ...

    @property
    def requires_approval(self) -> bool:
        """Real backends must return True."""
        ...

    def build_firmware(self, project_path: str) -> OperationResult:
        """Return the PC-local artifact_path when successful."""
        ...

    def flash_firmware(self, firmware_path: str) -> OperationResult:
        """Return verified and the actual remote_path."""
        ...

    def read_target_log(self, duration_s: float) -> OperationResult:
        """Collection success does not imply correct firmware behavior."""
        ...

    def run_hardware_test(
        self,
        test_id: str,
        params: dict[str, Any],
    ) -> OperationResult:
        """Keep measurement success separate from behavior passed."""
        ...
