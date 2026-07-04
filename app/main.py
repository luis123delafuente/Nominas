from fastapi import FastAPI

app = FastAPI(title="Nominas MEDIFORM PLUS")


@app.get("/")
def root():
    return {"status": "ok", "app": "nominas-mediformplus"}
