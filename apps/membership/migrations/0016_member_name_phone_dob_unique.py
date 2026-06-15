# Generated manually for composite member identity key

from django.db import migrations, models


def dedupe_member_identity_triples(apps, schema_editor):
    Member = apps.get_model('membership', 'Member')
    seen = {}
    duplicate_ids = []

    for member in Member.objects.order_by('id').iterator():
        key = (
            member.full_name or '',
            member.phone_number or '',
            member.date_of_birth,
        )
        if key in seen:
            duplicate_ids.append(member.id)
            continue
        seen[key] = member.id

    if duplicate_ids:
        Member.objects.filter(id__in=duplicate_ids).delete()


class Migration(migrations.Migration):
    # Dedupe deletes and ADD CONSTRAINT must not share one transaction on PostgreSQL.
    atomic = False

    dependencies = [
        ('membership', '0015_gymclass_karate_swimming_categories'),
    ]

    operations = [
        migrations.RunPython(dedupe_member_identity_triples, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='member',
            constraint=models.UniqueConstraint(
                fields=('full_name', 'phone_number', 'date_of_birth'),
                name='uniq_member_name_phone_dob',
            ),
        ),
    ]
