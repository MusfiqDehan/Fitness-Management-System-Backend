from django.db import migrations


class Migration(migrations.Migration):
    """Rebrand the support-request model away from the retired "FitHive" name.

    The replacement name is brand-neutral on purpose: the model records support
    requests addressed to whoever operates the platform, so the next product
    rename no longer has to drag the database along with it.

    This is the only file that still spells the old name — a rename operation
    has to say what it is renaming *from*. The historical migrations that
    created the table keep their original wording because they are the applied
    ledger of every existing tenant schema; rewriting them would desync
    migration state from the real tables.
    """

    dependencies = [
        ("main_app", "0003_query_optimization_indexes"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="FitHiveSupport",
            new_name="PlatformSupport",
        ),
        migrations.RenameIndex(
            model_name="platformsupport",
            new_name="idx_platform_status_created",
            old_name="idx_fithive_status_created",
        ),
    ]
