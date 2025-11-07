"""Entry point to run the admin web panel."""
from __future__ import annotations

import uvicorn

from app.config import ADMIN_WEB_BIND, ADMIN_WEB_PORT
from app.webadmin.server import app


if __name__ == "__main__":
    uvicorn.run(app, host=ADMIN_WEB_BIND, port=ADMIN_WEB_PORT, reload=False)
