import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("OWM_DASHBOARD_PORT", 8090))
    uvicorn.run("dashboard.server:app", host="127.0.0.1", reload=True, port=port)
