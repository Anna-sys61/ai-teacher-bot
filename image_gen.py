import aiohttp
import config

async def generate_image(prompt):
    url = "https://api.pixazo.ai/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {config.PIXAZO_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "prompt": prompt,
        "model": "flux-schnell",
        "size": "1024x1024"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as resp:
            result = await resp.json()
            return result["data"][0]["url"]