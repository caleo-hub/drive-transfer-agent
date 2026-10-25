from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from .safety import label, local_path, parse_drive_url, relative_path


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemInput(Model):
    source_ref: str = ""
    drive_url: str = ""
    folder_label: str | None = None

    @field_validator("drive_url")
    @classmethod
    def valid_url(cls, value):
        if value:
            parse_drive_url(value)
        return value

    @field_validator("folder_label")
    @classmethod
    def valid_label(cls, value):
        return label(value) if value is not None else None


class JobInput(Model):
    mode: Literal["inspect", "download", "verify"] = "download"
    items: list[ItemInput] = Field(min_length=1, max_length=100)
    destination_id: str | None = None
    conversation_id: str | None = None
    export_gdocs: StrictBool = True
    create_empty: StrictBool = True
    auto_repair: StrictBool = True


class DestinationInput(Model):
    name: str
    kind: Literal["local", "mega"]
    path: str

    @field_validator("name")
    @classmethod
    def valid_name(cls, v):
        return label(v)

    def validated_path(self):
        return (
            local_path(self.path) if self.kind == "local" else (relative_path(self.path) if self.path else "")
        )


class Preferences(Model):
    destination_id: str | None = None
    default_action: Literal["download", "inspect"] = "download"
    export_gdocs: StrictBool = True
    create_empty: StrictBool = True
    auto_repair: StrictBool = True
    reserve_bytes: int = Field(default=1024**3, ge=0)


class MessageInput(Model):
    text: str = Field(min_length=1, max_length=20000)
    request_id: str = Field(min_length=8, max_length=100)


class SetupInput(Model):
    kind: Literal["google", "mega", "model"]
    values: dict[str, str] = Field(default_factory=dict)


class QueueAction(Model):
    action: Literal["add", "rename", "reorder", "remove", "undo", "clear"]
    items: list[ItemInput] = Field(default_factory=list, max_length=100)
    item_id: str = ""
    name: str = ""
    order: list[str] = Field(default_factory=list)
