# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("TSP_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=8000, debug=debug)
