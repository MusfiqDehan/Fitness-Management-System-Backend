# Generated manually for multi-month coverage + line items + add-on migration

from django.db import migrations, models
from django.utils import timezone


def backfill_coverage_and_addons(apps, schema_editor):
    Payment = apps.get_model("membership", "Payment")
    MemberPackage = apps.get_model("membership", "MemberPackage")

    for payment in Payment.objects.all().iterator():
        months = payment.coverage_months or []
        if not months:
            dt = payment.payment_date or timezone.now()
            payment.coverage_months = [f"{dt.year:04d}-{dt.month:02d}"]
            payment.save(update_fields=["coverage_months"])

    for package in MemberPackage.objects.all().iterator():
        add_ons = package.add_ons or []
        if not add_ons:
            continue
        changed = False
        normalized = []
        for item in add_ons:
            if isinstance(item, str):
                name = item.strip()
                if name:
                    normalized.append({"name": name, "amount": "0.00"})
                    changed = True
            elif isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if not name:
                    changed = True
                    continue
                amount = item.get("amount", "0.00")
                normalized.append({"name": name, "amount": f"{amount}"})
            else:
                changed = True
        if changed:
            package.add_ons = normalized
            package.save(update_fields=["add_ons"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("membership", "0017_classenrollment"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="coverage_months",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="payment",
            name="line_items",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(backfill_coverage_and_addons, noop_reverse),
    ]
