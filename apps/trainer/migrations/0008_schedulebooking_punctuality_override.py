from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trainer', '0007_schedulebooking_source'),
    ]

    operations = [
        migrations.AddField(
            model_name='schedulebooking',
            name='punctuality_override',
            field=models.CharField(
                blank=True,
                choices=[
                    ('pending', 'Pending'),
                    ('on_time', 'On Time'),
                    ('late', 'Late'),
                    ('absent', 'Absent'),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
