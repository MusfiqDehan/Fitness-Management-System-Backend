"""Add pricing-customisation fields to PlatformPackage and introduce
PlatformPricingConfig singleton (platform-wide yearly discount default).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0009_backfill_platform_manager_email_settings"),
    ]

    operations = [
        # ── New fields on PlatformPackage ───────────────────────────────────
        migrations.AddField(
            model_name="platformpackage",
            name="badge_label",
            field=models.CharField(blank=True, default="", max_length=100,
                help_text="Top-right card badge text (e.g. '14 Days Free Trial', 'Most Popular')."),
        ),
        migrations.AddField(
            model_name="platformpackage",
            name="cta_label",
            field=models.CharField(blank=True, default="", max_length=100,
                help_text="Call-to-action button label shown on the pricing card."),
        ),
        migrations.AddField(
            model_name="platformpackage",
            name="setup_fee",
            field=models.CharField(blank=True, default="", max_length=100,
                help_text="Setup fee display text (e.g. 'Tk. 4990' or 'Custom')."),
        ),
        migrations.AddField(
            model_name="platformpackage",
            name="original_setup_fee",
            field=models.CharField(blank=True, default="", max_length=100,
                help_text="Strikethrough setup fee display text (e.g. 'Tk. 8990')."),
        ),
        migrations.AddField(
            model_name="platformpackage",
            name="original_price_monthly",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True,
                help_text="Strikethrough monthly price shown alongside the current price."),
        ),
        migrations.AddField(
            model_name="platformpackage",
            name="original_price_yearly",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True,
                help_text="Strikethrough yearly price shown when billing toggle is set to annually."),
        ),
        migrations.AddField(
            model_name="platformpackage",
            name="included_items",
            field=models.JSONField(blank=True, default=list,
                help_text="Manually typed 'What\u2019s included' list. Overrides auto-generated feature names when non-empty."),
        ),
        migrations.AddField(
            model_name="platformpackage",
            name="yearly_discount_percent",
            field=models.IntegerField(blank=True, null=True,
                help_text=(
                    "Yearly discount percentage (0\u2013100) shown as 'You Save X%' next to the billing toggle. "
                    "Leave blank to inherit the platform-wide default from PlatformPricingConfig."
                )),
        ),
        migrations.AddField(
            model_name="platformpackage",
            name="price_custom_label",
            field=models.CharField(blank=True, default="", max_length=100,
                help_text="If set, replaces the numeric price display (e.g. 'Custom' for Enterprise plans)."),
        ),
        migrations.AddField(
            model_name="platformpackage",
            name="price_period_label",
            field=models.CharField(blank=True, default="", max_length=100,
                help_text="If set, replaces the computed period string (e.g. '(10k \u2013 30k+)/Month')."),
        ),

        # ── PlatformPricingConfig singleton ────────────────────────────────
        migrations.CreateModel(
            name="PlatformPricingConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("default_yearly_discount_percent", models.IntegerField(default=0,
                    help_text=(
                        "Global yearly discount % shown as 'You Save X%' on the pricing page. "
                        "Individual packages can override this via their own yearly_discount_percent field."
                    ))),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Platform Pricing Config",
                "verbose_name_plural": "Platform Pricing Config",
            },
        ),
    ]
