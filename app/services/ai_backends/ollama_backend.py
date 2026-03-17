import httpx


class OllamaBackend:
    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self.base_url = base_url

    async def generate_text(self, model: str, system: str, prompt: str, timeout: float = 60.0) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system or ""},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        return data.get("message", {}).get("content", "").strip()
