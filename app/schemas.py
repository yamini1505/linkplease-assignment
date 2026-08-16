from pydantic import BaseModel


class RuleCreate(BaseModel):
    keyword: str
    dm_message: str