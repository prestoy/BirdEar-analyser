# birdear-web.py - BirdEar webserver
# Kjøres på RPi sammen med birdear-db-api.py
# Port: 8002
# Bruk: uvicorn birdear-web:app --host 0.0.0.0 --port 8002

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import yaml
import os

app = FastAPI()

# ----------------------------------------------------------------
# Konfigurasjon
# ----------------------------------------------------------------
#API_BASE_URL = "http://192.168.0.239:8001"
#API_BASE_URL = "https://birdmic-api.prestoy.cc"
API_BASE_URL = "https://birdear-api.prestoy.cc"

def load_config():
    with open("config-default.yaml") as f:
        return yaml.safe_load(f)

# ----------------------------------------------------------------
# Statiske filer (CSS, JS, bilder)
# Legg filer i mappen 'static/'
# ----------------------------------------------------------------
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ----------------------------------------------------------------
# HTML-templates
# Legg HTML-filer i mappen 'templates/'
# ----------------------------------------------------------------
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ----------------------------------------------------------------
# Ruter
# ----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "title": "BirdEar"
    })


@app.get("/lydavspiller", response_class=HTMLResponse)
async def lydavspiller(
    request: Request,
    from_date: str = "",
    to_date: str = "",
    min_conf: float = 0.7
):
    return templates.TemplateResponse("lydavspiller.html", {
        "request": request,
        "title": "Lydavspiller",
        "api_base_url": API_BASE_URL,
        "from_date": from_date,
        "to_date": to_date,
        "min_conf": min_conf
    })
