"""Check known official regional endpoints without printing credentials."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
from dotenv import dotenv_values
import requests

config = dotenv_values(Path(__file__).resolve().parents[1] / "agents/.env")


def check(endpoint):
    try:
        response = requests.get(
            endpoint + "/sessions", params={"limit": 1}, timeout=10,
            headers={"x-api-key": config["LANGSMITH_API_KEY"]},
        )
        info = requests.get(endpoint + "/info", timeout=10)
        return {"endpoint": endpoint, "status": response.status_code,
                "public_info_status": info.status_code,
                "headers": {k: v for k, v in response.headers.items()
                            if k.lower() in {"server", "content-type", "cf-ray", "via"}
                            or k.lower().startswith("x-openai")},
                "body_preview": response.text[:180] if response.status_code != 200 else "OK"}
    except Exception as error:
        return {"endpoint": endpoint, "error_type": type(error).__name__}


with ThreadPoolExecutor(max_workers=2) as pool:
    print(json.dumps(list(pool.map(check, [
        "https://aws.api.smith.langchain.com",
    ]))))
