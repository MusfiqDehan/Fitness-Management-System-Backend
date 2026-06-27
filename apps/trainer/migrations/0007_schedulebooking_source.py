from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trainer', '0006_query_optimization_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='schedulebooking',
            name='source',
            field=models.CharField(
                choices=[('member_booked', 'Member Booked'), ('admin_assigned', 'Admin Assigned')],
                default='member_booked',
                max_length=20,
            ),
        ),
    ]
