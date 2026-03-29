import os
import re

GITHUB_BASE = "https://github.com/TPEmist/Point-One-Percent/blob/main"

with open("README.md", "r", encoding="utf-8") as f:
    lines = f.readlines()

out_lines = []
for line in lines:
    # Insert PyPI note banner after the # title
    if line.startswith("# Point One Percent"):
        out_lines.append(line)
        out_lines.append(
            "\n> **Note**: This is the PyPI published documentation. "
            "For the full architecture diagrams and real UI screenshots, "
            "please visit the [GitHub Repository](https://github.com/TPEmist/Point-One-Percent).\n"
        )
        continue

    # Convert relative Markdown links to absolute GitHub URLs
    # Matches: [text](./path) or [text](./path#anchor)
    line = re.sub(
        r'\]\(\./([^)]+)\)',
        lambda m: f"]({GITHUB_BASE}/{m.group(1)})",
        line,
    )

    out_lines.append(line)

with open("README.pypi.md", "w", encoding="utf-8") as f:
    f.writelines(out_lines)

print("Generated README.pypi.md")
