from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from .models import AudioAnalysis, BatchUpload, Device

DEFAULT_AUDIO_ANALYSIS_RATE = Decimal("0.003")
DEFAULT_FAILED_ANALYSIS_RATE = Decimal("0.001")
DEFAULT_BATCH_RATE = Decimal("0.001")


def _rate(name: str, default: Decimal) -> Decimal:
    value = getattr(settings, name, default)
    try:
        return Decimal(str(value))
    except Exception:
        return default


AUDIO_ANALYSIS_RATE = _rate("BILLING_AUDIO_ANALYSIS_RATE", DEFAULT_AUDIO_ANALYSIS_RATE)
FAILED_ANALYSIS_RATE = _rate(
    "BILLING_FAILED_ANALYSIS_RATE", DEFAULT_FAILED_ANALYSIS_RATE
)
BATCH_RATE = _rate("BILLING_BATCH_RATE", DEFAULT_BATCH_RATE)


@dataclass(frozen=True)
class BillingPeriod:
    start: datetime
    end: datetime
    label: str
    is_current: bool
    days_in_period: int
    elapsed_days: int


def get_billing_period(year: int, month: int) -> BillingPeriod:
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    tz = timezone.get_current_timezone()
    start = timezone.make_aware(
        datetime.combine(first_day, datetime.min.time()), timezone=tz
    )
    end = timezone.make_aware(
        datetime.combine(last_day, datetime.max.time()), timezone=tz
    )

    now = timezone.localtime()
    is_current = now.year == year and now.month == month
    days_in_period = (last_day - first_day).days + 1
    elapsed_days = (
        max(1, min(now.day, days_in_period)) if is_current else days_in_period
    )

    return BillingPeriod(
        start=start,
        end=end,
        label=first_day.strftime("%B %Y"),
        is_current=is_current,
        days_in_period=days_in_period,
        elapsed_days=elapsed_days,
    )


def get_current_period() -> BillingPeriod:
    now = timezone.localtime()
    return get_billing_period(now.year, now.month)


def parse_period(value: Optional[str]) -> BillingPeriod:
    if value:
        try:
            year, month = value.split("-", 1)
            year = int(year)
            month = int(month)
            if 1 <= month <= 12 and 2000 <= year <= 2100:
                return get_billing_period(year, month)
        except (TypeError, ValueError):
            pass
    return get_current_period()


def _period_queryset(qs: QuerySet, period: BillingPeriod, field: str) -> QuerySet:
    return qs.filter(**{f"{field}__gte": period.start, f"{field}__lte": period.end})


def calculate_billing(user, period: BillingPeriod) -> dict:
    batches = _period_queryset(
        BatchUpload.objects.filter(user=user), period, "uploaded_at"
    )
    analyses = _period_queryset(
        AudioAnalysis.objects.filter(batch__user=user), period, "created_at"
    )

    successful = analyses.filter(status=AudioAnalysis.ProcessingStatus.SUCCESS)
    failed = analyses.filter(status=AudioAnalysis.ProcessingStatus.FAILED)

    batch_count = batches.count()
    successful_count = successful.count()
    failed_count = failed.count()
    device_count = Device.objects.filter(user=user).count()
    active_device_count = Device.objects.filter(
        user=user, last_seen__gte=period.start, last_seen__lte=period.end
    ).count()

    services = [
        {
            "key": "audio_analysis",
            "name": "Audio analysis",
            "description": "Successfully processed audio clips",
            "usage": successful_count,
            "unit": "clips",
            "rate": AUDIO_ANALYSIS_RATE,
            "cost": Decimal(successful_count) * AUDIO_ANALYSIS_RATE,
            "metered": True,
        },
        {
            "key": "failed_analysis",
            "name": "Failed processing",
            "description": "Processing attempts that failed after being submitted",
            "usage": failed_count,
            "unit": "clips",
            "rate": FAILED_ANALYSIS_RATE,
            "cost": Decimal(failed_count) * FAILED_ANALYSIS_RATE,
            "metered": True,
        },
        {
            "key": "batch_processing",
            "name": "Batch processing",
            "description": "Uploaded processing batches",
            "usage": batch_count,
            "unit": "batches",
            "rate": BATCH_RATE,
            "cost": Decimal(batch_count) * BATCH_RATE,
            "metered": True,
        },
        {
            "key": "devices",
            "name": "Device usage",
            "description": "Devices registered to your account",
            "usage": device_count,
            "unit": "devices",
            "rate": Decimal("0"),
            "cost": Decimal("0"),
            "metered": False,
            "note": "No device fee configured yet",
        },
    ]

    actual_total = sum((item["cost"] for item in services), Decimal("0"))

    if period.is_current:
        projected_total = (
            actual_total * Decimal(period.days_in_period) / Decimal(period.elapsed_days)
        )
    else:
        projected_total = actual_total

    return {
        "period": period,
        "services": services,
        "actual_total": actual_total,
        "projected_total": projected_total,
        "currency": "USD",
        "summary": {
            "batches": batch_count,
            "processed_clips": successful_count,
            "failed_clips": failed_count,
            "devices": device_count,
            "active_devices": active_device_count,
        },
    }
