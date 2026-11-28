#!/usr/bin/env python3

import json
import os
import sys


def main() -> int:
    line = os.environ.get("CARNIVORE_AGY_LAUNCH_LINE", "").strip()
    answer = {"injectSteps": [{"systemMessage": {"systemMessage": line}}]} if line else {}
    sys.stdout.write(json.dumps(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
