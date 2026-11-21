from importlib.resources import files

try:
    from importlib.resources.abc import Traversable
except ModuleNotFoundError:  # Python 3.10
    from importlib.abc import Traversable


def resource_file(*parts: str) -> Traversable:
    target = files("bokpilot").joinpath("resources", *parts)
    if not target.is_file():
        raise FileNotFoundError("Packaged Bokpilot resource was not found.")
    return target
