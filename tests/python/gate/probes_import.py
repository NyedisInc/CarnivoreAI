
from __future__ import annotations

import json


def main() -> None:
    import src.main as main_module  # noqa: PLC0415
    from src.core.mcp import tools  # noqa: PLC0415
    from src.cplugs.host import runtime  # noqa: PLC0415

    print(json.dumps({"imported": True, "plugins": sorted(d.id for d in runtime.definitions()),
                      "routes": len(main_module.app.routes), "tools": len(tools.tool_names())}))


if __name__ == "__main__":
    main()
