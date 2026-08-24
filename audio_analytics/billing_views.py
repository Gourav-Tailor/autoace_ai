from datetime import date

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from .billing import calculate_billing, parse_period


class BillingView(LoginRequiredMixin, TemplateView):
    template_name = "audio_analytics/billing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        billing = calculate_billing(
            self.request.user,
            parse_period(self.request.GET.get("month")),
        )

        period = billing["period"]
        current = date.today()
        previous_month = period.start.date().replace(day=1)
        if previous_month.month == 1:
            previous_month = previous_month.replace(
                year=previous_month.year - 1, month=12
            )
        else:
            previous_month = previous_month.replace(month=previous_month.month - 1)

        next_month = period.start.date().replace(day=28)
        next_month = next_month.replace(day=1)
        if next_month.month == 12:
            next_month = next_month.replace(year=next_month.year + 1, month=1)
        else:
            next_month = next_month.replace(month=next_month.month + 1)

        context.update(
            billing=billing,
            period=period,
            previous_month=previous_month.strftime("%Y-%m"),
            next_month=next_month.strftime("%Y-%m"),
            can_go_next=(
                next_month.year < current.year
                or (
                    next_month.year == current.year
                    and next_month.month <= current.month
                )
            ),
        )
        return context
