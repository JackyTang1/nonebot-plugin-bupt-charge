"""Optional public-API settings; no account or Cookie is needed."""

from pydantic import BaseModel, Field


class Config(BaseModel):
    bupt_charge_api_url: str = "https://wx.jwnzn.com/njjwn"
    bupt_charge_timeout_seconds: float = Field(default=8.0, gt=0)
    bupt_charge_cache_seconds: float = Field(default=30.0, ge=0)
