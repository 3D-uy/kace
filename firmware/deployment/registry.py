"""Explicit allow-listed deployment method registry."""

from .manual import ManualDeploymentMethod
from .models import DeploymentMethodId
from .usb import UsbDeploymentMethod


class DeploymentMethodRegistry:
    def __init__(self):
        self._methods = {
            DeploymentMethodId.MANUAL: ManualDeploymentMethod(),
            DeploymentMethodId.USB: UsbDeploymentMethod(),
        }

    def get(self, method: DeploymentMethodId):
        try:
            return self._methods[DeploymentMethodId(method)]
        except (KeyError, ValueError) as exc:
            raise ValueError(f"deployment method is not registered: {method}") from exc

    def ids(self) -> tuple[DeploymentMethodId, ...]:
        return tuple(self._methods)
