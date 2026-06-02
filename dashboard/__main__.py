import uvicorn

if __name__ == "__main__":
    uvicorn.run("dashboard.server:app", host="127.0.0.1", reload=True, port=8090)
