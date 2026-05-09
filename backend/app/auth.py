from fastapi import Depends, Header, HTTPException

from app.config import Settings, get_settings


async def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.api_key:
        return  # auth disabled when api_key is not configured
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
