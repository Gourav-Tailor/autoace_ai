import hashlib
import json
from decimal import Decimal

import razorpay
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import View

from .billing import calculate_billing, get_current_period
from .models import Payment


def _client():
    key_id = getattr(settings, "RAZORPAY_KEY_ID", "")
    secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
    if not key_id or not secret:
        raise RuntimeError("Razorpay credentials are not configured")
    return razorpay.Client(auth=(key_id, secret))


def _paise(amount: Decimal) -> int:
    return int((amount * Decimal("100")).quantize(Decimal("1")))


def _idempotency_key(user_id, month, amount):
    return hashlib.sha256(
        f"{user_id}:{month.isoformat()}:{amount}".encode()
    ).hexdigest()


class CreateRazorpayOrderView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        billing = calculate_billing(request.user, get_current_period())

        if billing["currency"] != "INR":
            return JsonResponse(
                {"error": "Razorpay checkout requires BILLING_CURRENCY=INR."},
                status=400,
            )

        amount = billing["outstanding_total"]
        if amount <= 0:
            return JsonResponse(
                {"error": "There is no outstanding amount to pay."}, status=400
            )

        month = billing["period"].start.date().replace(day=1)
        key = _idempotency_key(request.user.pk, month, amount)

        try:
            with transaction.atomic():
                existing = Payment.objects.filter(idempotency_key=key).first()
                if existing and existing.status == Payment.Status.CREATED:
                    return JsonResponse(
                        {
                            "key_id": settings.RAZORPAY_KEY_ID,
                            "order_id": existing.razorpay_order_id,
                            "amount": _paise(existing.amount),
                            "currency": existing.currency,
                        }
                    )

                order = _client().order.create(
                    {
                        "amount": _paise(amount),
                        "currency": "INR",
                        "receipt": f"audoack-{request.user.pk}-{month:%Y%m}-{key[:12]}",
                        "notes": {
                            "user_id": str(request.user.pk),
                            "billing_month": month.isoformat(),
                        },
                    }
                )

                payment = Payment.objects.create(
                    user=request.user,
                    billing_month=month,
                    amount=amount,
                    currency="INR",
                    idempotency_key=key,
                    razorpay_order_id=order["id"],
                )

            return JsonResponse(
                {
                    "key_id": settings.RAZORPAY_KEY_ID,
                    "order_id": payment.razorpay_order_id,
                    "amount": _paise(payment.amount),
                    "currency": payment.currency,
                }
            )
        except RuntimeError as exc:
            return JsonResponse({"error": str(exc)}, status=503)
        except razorpay.errors.BadRequestError:
            return JsonResponse(
                {"error": "Razorpay rejected the order request."}, status=502
            )


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        return JsonResponse({"error": "Webhook secret is not configured."}, status=503)

    try:
        _client().utility.verify_webhook_signature(
            request.body.decode("utf-8"),
            request.headers.get("X-Razorpay-Signature", ""),
            secret,
        )
    except Exception:
        return JsonResponse({"error": "Invalid webhook signature."}, status=400)

    try:
        payload = json.loads(request.body)
        event = payload.get("event")
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        order_id = entity.get("order_id")

        if event in {"payment.captured", "order.paid"} and order_id:
            payment = Payment.objects.get(razorpay_order_id=order_id)
            payment.status = Payment.Status.PAID
            payment.razorpay_payment_id = (
                entity.get("id") or payment.razorpay_payment_id
            )
            payment.paid_at = payment.paid_at or timezone.now()
            payment.save(update_fields=["status", "razorpay_payment_id", "paid_at"])

        elif event == "payment.failed" and order_id:
            Payment.objects.filter(
                razorpay_order_id=order_id,
                status=Payment.Status.CREATED,
            ).update(status=Payment.Status.FAILED)

    except Payment.DoesNotExist:
        return JsonResponse({"error": "Unknown Razorpay order."}, status=404)
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid webhook payload."}, status=400)

    return JsonResponse({"status": "ok"})
