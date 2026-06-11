from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trainer', '0004_trainerinvitation_branch'),
    ]

    operations = [
        migrations.AddField(
            model_name='trainerschedule',
            name='day_of_week',
            field=models.CharField(
                blank=True,
                choices=[
                    ('saturday', 'Saturday'),
                    ('sunday', 'Sunday'),
                    ('monday', 'Monday'),
                    ('tuesday', 'Tuesday'),
                    ('wednesday', 'Wednesday'),
                    ('thursday', 'Thursday'),
                    ('friday', 'Friday'),
                ],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='trainerschedule',
            name='scheduled_date',
            field=models.DateField(blank=True, null=True),
        ),
    ]
