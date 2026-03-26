from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("aegis-pay")
except PackageNotFoundError:
    __version__ = "unknown"
