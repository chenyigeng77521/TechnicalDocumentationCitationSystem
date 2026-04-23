from fastapi import FastAPI

app = FastAPI(title="chunking-rag-py")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
