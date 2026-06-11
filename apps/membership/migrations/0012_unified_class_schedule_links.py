import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('membership', '0011_member_branch'),
        ('trainer', '0005_unified_schedule_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='gymclass',
            name='trainer_profile',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='gym_classes',
                to='trainer.trainerprofile',
            ),
        ),
        migrations.AddField(
            model_name='gymclass',
            name='trainer_class',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='gym_class',
                to='trainer.trainerclass',
            ),
        ),
        migrations.AddField(
            model_name='gymschedule',
            name='trainer_profile',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='gym_schedules',
                to='trainer.trainerprofile',
            ),
        ),
        migrations.AddField(
            model_name='gymschedule',
            name='recurrence_mode',
            field=models.CharField(
                choices=[('weekly', 'Weekly'), ('one_off', 'One-off')],
                default='weekly',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='gymschedule',
            name='scheduled_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='gymschedule',
            name='trainer_schedule',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='gym_schedule',
                to='trainer.trainerschedule',
            ),
        ),
    ]
