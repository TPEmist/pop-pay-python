"""
Hatchling build hook for compiling Cython extensions.

The _COMPILED_SALT in _vault_core.pyx is replaced at build time by the
POP_VAULT_COMPILED_SALT environment variable (set as a GitHub Actions secret).
If the env var is not set, the .so is built with _COMPILED_SALT = None
(falls back to the public OSS salt at runtime).
"""
import os
import subprocess
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        compiled_salt = os.environ.get("POP_VAULT_COMPILED_SALT", "")
        pyx_path = Path("pop_pay/engine/_vault_core.pyx")
        if not pyx_path.exists():
            return

        # Tell hatchling this wheel contains a compiled extension (platform-specific)
        build_data['pure_python'] = False
        build_data['infer_tag'] = True

        if compiled_salt:
            # Inject the secret salt into the .pyx before compiling
            source = pyx_path.read_text()
            patched = source.replace(
                '_COMPILED_SALT = None  # Replaced by CI: b"<SECRET_INJECTED_AT_BUILD_TIME>"',
                f'_COMPILED_SALT = {repr(compiled_salt.encode())}'
            )
            pyx_path.write_text(patched)

        # Compile the Cython extension
        try:
            result = subprocess.run(
                [sys.executable, "setup_cython.py", "build_ext", "--inplace"],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print("Cython compilation stdout:")
                print(result.stdout[-3000:] if result.stdout else "(none)")
                print("Cython compilation stderr:")
                print(result.stderr[-3000:] if result.stderr else "(none)")
                raise RuntimeError(f"setup_cython.py exited with code {result.returncode}")
            print("Cython compilation succeeded.")
            print(result.stdout[-1000:] if result.stdout else "")
        except Exception as e:
            print(f"ERROR: Cython compilation failed: {e}. Falling back to pure Python.")
        finally:
            if compiled_salt:
                # Restore original .pyx (don't commit the secret)
                pyx_path.write_text(source)
