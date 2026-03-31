"""setuptools config for Cython extension compilation."""
from setuptools import setup, Extension

try:
    from Cython.Build import cythonize
    extensions = cythonize([
        Extension(
            "pop_pay.engine._vault_core",
            sources=["pop_pay/engine/_vault_core.pyx"],
            extra_compile_args=["-O2"],
        )
    ], compiler_directives={"language_level": "3"})
except ImportError:
    extensions = []

setup(ext_modules=extensions, packages=[])
