"""Request bodies. Prices never come from the client."""
from __future__ import annotations

import re
import unicodedata
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

PHONE_RE = re.compile(r"^[6-9]\d{9}$")


class OrderItemIn(BaseModel):
    id: str = Field(min_length=1, max_length=20)
    qty: int = Field(ge=1, le=20)


class OrderIn(BaseModel):
    name: str
    phone: str
    order_type: Literal["Dine in", "Takeaway"]
    table: Optional[int] = None
    items: list[OrderItemIn] = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Enter your name.")
        if len(v) > 40:
            raise ValueError("Name is too long.")
        if any(unicodedata.category(c).startswith("C") for c in v):
            raise ValueError("Name has characters we cannot accept.")
        return v

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        v = re.sub(r"\D", "", v)
        if not PHONE_RE.match(v):
            raise ValueError("Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.")
        return v


class WaiterOrderIn(BaseModel):
    """An order a waiter takes for a guest. Name and number are optional: the waiter may not have them."""
    name: str = ""
    phone: str = ""
    order_type: Literal["Dine in", "Takeaway"] = "Dine in"
    table: Optional[int] = None
    items: list[OrderItemIn] = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return OrderIn.clean_name(v) if v.strip() else ""

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v: str) -> str:
        return OrderIn.clean_phone(v) if v.strip() else ""


class StaffEditIn(BaseModel):
    """A waiter's new list of dishes for an order. An empty list cancels it."""
    items: list[OrderItemIn] = Field(max_length=40)


class OrderEditIn(BaseModel):
    """The guest's new list for an order they placed. An empty list cancels it."""
    edit_key: str = Field(min_length=10, max_length=64)
    items: list[OrderItemIn] = Field(max_length=40)


class StatusIn(BaseModel):
    status: Literal["new", "preparing", "ready", "served", "cancelled"]


class AvailabilityIn(BaseModel):
    available: bool


# ---------- admin ----------
def _text(v: str, label: str, lo: int, hi: int) -> str:
    v = " ".join(v.split())
    if len(v) < lo:
        raise ValueError(f"{label} is too short." if lo > 1 else f"Enter {label.lower()}.")
    if len(v) > hi:
        raise ValueError(f"{label} is too long (at most {hi} characters).")
    if any(unicodedata.category(c).startswith("C") for c in v):
        raise ValueError(f"{label} has characters we cannot accept.")
    return v


class MenuItemIn(BaseModel):
    name: str
    category: str
    description: str = ""
    price: int = Field(ge=0, le=100000)
    veg: bool = False
    spice: int = Field(default=0, ge=0, le=3)
    hue: Optional[int] = Field(default=None, ge=0, le=360)
    available: bool = True
    no_gst: bool = False          # packaged item sold at MRP: no GST added on the bill

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        return _text(v, "Name", 2, 60)

    @field_validator("category")
    @classmethod
    def _c(cls, v: str) -> str:
        return _text(v, "Category", 2, 30)

    @field_validator("description")
    @classmethod
    def _d(cls, v: str) -> str:
        return _text(v, "Description", 0, 200) if v.strip() else ""


class MenuItemPatch(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = Field(default=None, ge=0, le=100000)
    veg: Optional[bool] = None
    spice: Optional[int] = Field(default=None, ge=0, le=3)
    hue: Optional[int] = Field(default=None, ge=0, le=360)
    available: Optional[bool] = None
    no_gst: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return None if v is None else _text(v, "Name", 2, 60)

    @field_validator("category")
    @classmethod
    def _c(cls, v):
        return None if v is None else _text(v, "Category", 2, 30)

    @field_validator("description")
    @classmethod
    def _d(cls, v):
        return None if v is None else (_text(v, "Description", 0, 200) if v.strip() else "")


class ImageIn(BaseModel):
    """A dish photo as a data URL (the admin screen shrinks it first), and who took it."""
    data: str = Field(min_length=30, max_length=3_000_000)
    credit: str = Field(default="", max_length=300)


class PaymentIn(BaseModel):
    """The shop's UPI QR as a data URL (optional) and its UPI ID (optional, empty clears it)."""
    qr: Optional[str] = Field(default=None, max_length=3_000_000)
    upi_id: Optional[str] = Field(default=None, max_length=130)


class MoveIn(BaseModel):
    direction: Literal["up", "down"]


# ---------- on-screen settings and first-run setup ----------
_GSTIN_RE = re.compile(r"^[0-9A-Z]{15}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]{1,100}$")
_HEX_RE = re.compile(r"^(0x)?[0-9a-fA-F]{1,4}$")
_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?$")
_PIN_RE = re.compile(r"^[A-Za-z0-9]{4,20}$")


class _SettingsBase(BaseModel):
    shop_name: Optional[str] = None
    shop_addr: Optional[str] = None
    gstin: Optional[str] = None
    gst_percent: Optional[int] = Field(default=None, ge=0, le=28)
    tables: Optional[int] = Field(default=None, ge=1, le=50)
    printer: Optional[Literal["none", "file", "network", "usb", "windows"]] = None
    printer_name: Optional[str] = None
    printer_host: Optional[str] = None
    printer_port: Optional[int] = Field(default=None, ge=1, le=65535)
    usb_vendor: Optional[str] = None
    usb_product: Optional[str] = None
    cols: Optional[Literal[32, 42, 48]] = None
    public_url: Optional[str] = None
    staff_pin: Optional[str] = None
    admin_pin: Optional[str] = None

    @field_validator("shop_name")
    @classmethod
    def _v_shop(cls, v):
        return None if v is None else _text(v, "Shop name", 2, 60)

    @field_validator("shop_addr")
    @classmethod
    def _v_addr(cls, v):
        return None if v is None else (_text(v, "Address", 0, 120) if v.strip() else "")

    @field_validator("printer_name")
    @classmethod
    def _v_pname(cls, v):
        return None if v is None else (_text(v, "Printer name", 0, 100) if v.strip() else "")

    @field_validator("gstin")
    @classmethod
    def _v_gstin(cls, v):
        if v is None:
            return None
        v = v.strip().upper()
        if v and not _GSTIN_RE.match(v):
            raise ValueError("GSTIN must be 15 letters and digits, or left empty.")
        return v

    @field_validator("printer_host")
    @classmethod
    def _v_host(cls, v):
        if v is None:
            return None
        v = v.strip()
        if v and not _HOST_RE.match(v):
            raise ValueError("Printer address must be an IP address or name, for example 192.168.1.50.")
        return v

    @field_validator("usb_vendor", "usb_product")
    @classmethod
    def _v_hex(cls, v):
        if v is None:
            return None
        v = v.strip()
        if not v:
            return ""
        if not _HEX_RE.match(v):
            raise ValueError("USB ids are hexadecimal, for example 0x04b8.")
        return "0x%04x" % int(v.lower().replace("0x", ""), 16)

    @field_validator("public_url")
    @classmethod
    def _v_url(cls, v):
        if v is None:
            return None
        v = v.strip().rstrip("/")
        if v and not _ORIGIN_RE.match(v):
            raise ValueError("The guest address must look like http://192.168.1.20:8000 or https://order.example.com")
        return v

    @field_validator("staff_pin", "admin_pin")
    @classmethod
    def _v_pin(cls, v):
        if v is None:
            return None
        if not _PIN_RE.match(v):
            raise ValueError("A PIN must be 4 to 20 letters or digits.")
        return v


class SettingsIn(_SettingsBase):
    """Owner changes settings on screen. Leave a field out to keep it as it is."""


class SetupIn(_SettingsBase):
    """First-run setup. The essentials are required."""
    shop_name: str
    staff_pin: str
    admin_pin: str
    sample_menu: bool = True
