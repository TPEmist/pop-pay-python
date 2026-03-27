import os

with open("README.md", "r", encoding="utf-8") as f:
    lines = f.readlines()

out_lines = []
for i, line in enumerate(lines):
    out_lines.append(line)
    
    # Insert the redirect link after the # title
    if line.startswith("# Point One Percent"):
        out_lines.append("\n> **Note**: This is the PyPI published documentation. For the full architecture diagrams and real UI screenshots, please visit the [GitHub Repository](https://github.com/TPEmist/Point-One-Percent).\n")

with open("README.pypi.md", "w", encoding="utf-8") as f:
    f.writelines(out_lines)

print("Generated README.pypi.md")
