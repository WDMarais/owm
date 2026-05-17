import uvicorn

if __name__ == "__main__":
    uvicorn.run("dashboard.dev_server:app", host="0.0.0.0", reload=True, port=8200)
